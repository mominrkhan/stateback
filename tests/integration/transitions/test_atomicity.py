from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AuditEventType, OperationState
from stateback.persistence.uow import UnitOfWork, unit_of_work
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService
from tests.integration.transitions.conftest import (
    command_for,
    prepare_source,
)
from tests.unit.domain.fixtures import OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_rollback_leaves_no_state_audit_or_outbox(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.POLICY_ALLOW)
    command = command_for(scenario, TransitionKind.POLICY_ALLOW)
    uow = UnitOfWork(uow_factory())
    try:
        result = TransitionService().apply(uow, command)
        assert result.outcome is TransitionOutcome.APPLIED
        raise RuntimeError("force rollback")
    except RuntimeError:
        uow.rollback()
    finally:
        uow.close()
    with unit_of_work(uow_factory) as reload:
        assert reload.operations.get(scenario.operation.operation_id) is not None
        events = reload.audit_events.list_for_operation(scenario.operation.operation_id)
        assert all(
            item.event_type is not AuditEventType.POLICY_EVALUATED for item in events
        )
        assert reload.outbox_events.list_pending_for_claim(10) == []
        loaded = reload.operations.get(scenario.operation.operation_id)
        assert loaded is not None
        assert loaded.state is OperationState.PENDING_POLICY


def test_commit_persists_state_audit_and_outbox_together(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.POLICY_ALLOW)
    result = scenario.apply(command_for(scenario, TransitionKind.POLICY_ALLOW))
    assert result.outcome is TransitionOutcome.APPLIED
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
        assert loaded is not None
        assert loaded.state is OperationState.READY
        events = uow.audit_events.list_for_operation(OP_ID)
        assert any(
            item.event_type is AuditEventType.POLICY_EVALUATED for item in events
        )
        assert events[-1].event_type is AuditEventType.OPERATION_TRANSITIONED
        pending = uow.outbox_events.list_pending_for_claim(10)
        assert len(pending) == 1


def test_unknown_history_remains_after_reconcile_to_succeeded(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.EXECUTION_UNKNOWN)
    scenario.apply(command_for(scenario, TransitionKind.EXECUTION_UNKNOWN))
    with unit_of_work(uow_factory) as uow:
        before = [
            item.event_type for item in uow.audit_events.list_for_operation(OP_ID)
        ]
    assert AuditEventType.EXECUTION_EVIDENCE_RECORDED in before
    scenario.apply(command_for(scenario, TransitionKind.UNKNOWN_RECONCILE_APPLIED))
    with unit_of_work(uow_factory) as uow:
        after = uow.audit_events.list_for_operation(OP_ID)
        types = [item.event_type for item in after]
        assert AuditEventType.EXECUTION_EVIDENCE_RECORDED in types
        loaded = uow.operations.get(OP_ID)
        assert loaded is not None
        assert loaded.state is OperationState.SUCCEEDED
