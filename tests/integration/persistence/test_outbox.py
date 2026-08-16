from __future__ import annotations

from threading import Barrier, Thread

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import CONTRACT_VERSION, OutboxState, WorkCommand
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.messaging import OutboxEvent
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.integration.persistence.conftest import (
    OUTBOX_ID_2,
    make_operation,
    make_outbox,
)
from tests.unit.domain.fixtures import LATER, OP_ID, OUTBOX_ID, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_insert_pending(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.outbox_events.insert(make_outbox())
    with unit_of_work(uow_factory) as uow:
        loaded = uow.outbox_events.get(OUTBOX_ID)
    assert loaded is not None
    assert loaded.state is OutboxState.PENDING
    assert loaded.published_at is None


def test_mark_published(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.outbox_events.insert(make_outbox())
        uow.outbox_events.mark_published(OUTBOX_ID, LATER)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.outbox_events.get(OUTBOX_ID)
    assert loaded is not None
    assert loaded.state is OutboxState.PUBLISHED
    assert loaded.published_at == LATER


def test_mark_published_idempotent(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.outbox_events.insert(make_outbox())
        uow.outbox_events.mark_published(OUTBOX_ID, LATER)
        uow.outbox_events.mark_published(OUTBOX_ID, TS)


def test_cannot_insert_pending_with_published_at() -> None:
    with pytest.raises(ContractValidationError) as exc:
        OutboxEvent(
            contract_version=CONTRACT_VERSION,
            event_id=OUTBOX_ID,
            state=OutboxState.PENDING,
            aggregate_type="operation",
            aggregate_id=OP_ID,
            operation_version=1,
            command=WorkCommand.EXECUTE,
            created_at=TS,
            published_at=LATER,
            correlation_id=None,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_list_pending_for_claim_skips_published(
    uow_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.outbox_events.insert(make_outbox())
        uow.outbox_events.insert(make_outbox(event_id=OUTBOX_ID_2))
        uow.outbox_events.mark_published(OUTBOX_ID, LATER)
    with unit_of_work(uow_factory) as uow:
        pending = uow.outbox_events.list_pending_for_claim(10)
    assert [item.event_id for item in pending] == [OUTBOX_ID_2]


def test_claim_skip_locked_concurrent(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.outbox_events.insert(make_outbox())
        uow.outbox_events.insert(make_outbox(event_id=OUTBOX_ID_2))

    barrier = Barrier(2)
    claimed: list[list[str]] = [[], []]

    def worker(index: int) -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        try:
            barrier.wait()
            events = uow.outbox_events.list_pending_for_claim(1)
            claimed[index] = [event.event_id.value for event in events]
            barrier.wait()
        finally:
            uow.rollback()
            uow.close()
            engine.dispose()

    threads = [Thread(target=worker, args=(0,)), Thread(target=worker, args=(1,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    ids = claimed[0] + claimed[1]
    assert sorted(ids) == sorted([OUTBOX_ID.value, OUTBOX_ID_2.value])
    assert claimed[0] != claimed[1]
