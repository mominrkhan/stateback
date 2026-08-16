from __future__ import annotations

from dataclasses import replace
from threading import Barrier, Thread

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.exceptions import (
    ConcurrencyConflictError,
    DuplicateKeyError,
)
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.integration.persistence.conftest import (
    AUDIT_ID_2,
    make_audit,
    make_operation,
)
from tests.unit.domain.fixtures import LATER, OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_concurrent_cas_one_winner(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())

    barrier = Barrier(2)
    outcomes: list[str] = []

    def worker() -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        try:
            barrier.wait()
            locked = uow.operations.get_for_update(OP_ID)
            assert locked is not None
            uow.operations.update_cas(
                1,
                replace(
                    locked, version=2, state=OperationState.READY, updated_at=LATER
                ),
            )
            uow.commit()
            outcomes.append("ok")
        except ConcurrencyConflictError:
            uow.rollback()
            outcomes.append("conflict")
        finally:
            uow.close()
            engine.dispose()

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "ok"]
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
    assert loaded is not None
    assert loaded.version == 2


def test_concurrent_duplicate_operation_id(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []

    def worker() -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        try:
            barrier.wait()
            uow.operations.insert(make_operation())
            uow.commit()
            outcomes.append("ok")
        except DuplicateKeyError:
            uow.rollback()
            outcomes.append("dup")
        finally:
            uow.close()
            engine.dispose()

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["dup", "ok"]
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) is not None


def test_concurrent_audit_sequence_without_lock(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())

    barrier = Barrier(2)
    outcomes: list[str] = []

    def worker(use_second_id: bool) -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        try:
            barrier.wait()
            event = (
                make_audit(audit_event_id=AUDIT_ID_2, sequence=1)
                if use_second_id
                else make_audit()
            )
            uow.audit_events.append(event)
            uow.commit()
            outcomes.append("ok")
        except DuplicateKeyError as exc:
            uow.rollback()
            assert exc.reason_code == "duplicate_audit_sequence"
            outcomes.append("dup")
        finally:
            uow.close()
            engine.dispose()

    threads = [
        Thread(target=worker, args=(False,)),
        Thread(target=worker, args=(True,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["dup", "ok"]
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(OP_ID)
    assert len(events) == 1
    assert events[0].sequence == 1
