from __future__ import annotations

from dataclasses import replace
from threading import Barrier, Thread

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError, InternalError
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import ApprovalState
from stateback.persistence.exceptions import (
    AppendOnlyViolationError,
    ConcurrencyConflictError,
)
from stateback.persistence.models import PolicyDecisionRow
from stateback.persistence.types import opaque_to_uuid
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.integration.persistence.conftest import (
    make_approval,
    make_operation,
    make_policy,
)
from tests.unit.domain.fixtures import APPROVAL_ID, LATER, POLICY_ID, REQUESTER

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_policy_insert_and_list(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    decision = make_policy(intent_digest=operation.intent.intent_digest)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.policy_decisions.insert(decision)
    with unit_of_work(uow_factory) as uow:
        listed = uow.policy_decisions.list_for_operation(operation.operation_id)
    assert listed == [decision]


def test_policy_update_blocked_by_trigger(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    decision = make_policy(intent_digest=operation.intent.intent_digest)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.policy_decisions.insert(decision)
    uow = UnitOfWork(uow_factory())
    try:
        with pytest.raises(
            (AppendOnlyViolationError, IntegrityError, InternalError, DBAPIError)
        ):
            uow.session.execute(
                update(PolicyDecisionRow)
                .where(
                    PolicyDecisionRow.policy_decision_id == opaque_to_uuid(POLICY_ID)
                )
                .values(verdict="ALLOW")
            )
            uow.session.flush()
    finally:
        uow.rollback()
        uow.close()


def test_approval_pending_round_trip(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    decision = make_policy(intent_digest=operation.intent.intent_digest)
    approval = make_approval()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.policy_decisions.insert(decision)
        uow.approvals.insert(approval)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.approvals.get(APPROVAL_ID)
    assert loaded == approval
    assert loaded is not None
    assert loaded.state is ApprovalState.PENDING


def test_approval_cas_approve(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    decision = make_policy(intent_digest=operation.intent.intent_digest)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.policy_decisions.insert(decision)
        uow.approvals.insert(make_approval())
    approved = replace(
        make_approval(state=ApprovalState.APPROVED),
        decided_at=LATER,
        decided_by=REQUESTER,
        reason="approved",
    )
    with unit_of_work(uow_factory) as uow:
        uow.approvals.update_cas_state(approved, ApprovalState.PENDING)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.approvals.get(APPROVAL_ID)
    assert loaded is not None
    assert loaded.state is ApprovalState.APPROVED
    assert loaded.decided_at == LATER
    assert loaded.decided_by == REQUESTER


def test_approval_cas_conflict(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    from stateback.persistence.engine import create_engine_from_url, session_factory

    operation = make_operation()
    decision = make_policy(intent_digest=operation.intent.intent_digest)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.policy_decisions.insert(decision)
        uow.approvals.insert(make_approval())

    approved = replace(
        make_approval(state=ApprovalState.APPROVED),
        decided_at=LATER,
        decided_by=REQUESTER,
        reason="approved",
    )
    barrier = Barrier(2)
    outcomes: list[str] = []

    def worker() -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        try:
            barrier.wait()
            uow.approvals.update_cas_state(approved, ApprovalState.PENDING)
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
