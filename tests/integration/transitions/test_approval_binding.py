from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    OperationState,
    OutboxState,
    WorkCommand,
)
from stateback.domain.policy import Approval
from stateback.domain.time import UtcTimestamp
from stateback.persistence.uow import unit_of_work
from stateback.transitions.commands import ApprovalGrant, ApprovalReject
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    APPROVER,
    _create,
    _require_approval,
    apply_committed,
)
from tests.unit.domain.fixtures import LATER, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_grant_with_digest_mismatch_rejected(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = _require_approval(_create(uow_factory))
    assert scenario.approval is not None
    granted = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=scenario.approval.approval_id,
        operation_id=scenario.operation.operation_id,
        operation_version=scenario.operation.version,
        intent_digest="0" * 64,
        policy_decision_id=scenario.approval.policy_decision_id,
        state=ApprovalState.APPROVED,
        requested_at=scenario.approval.requested_at,
        expires_at=None,
        decided_at=LATER,
        decided_by=APPROVER,
        reason="approved",
    )
    result = apply_committed(
        uow_factory,
        ApprovalGrant(
            kind=TransitionKind.APPROVAL_GRANT,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=APPROVER,
            correlation_id=None,
            reason_code="grant",
            transition_audit_event_id=scenario.ids.next(),
            approval=granted,
            approval_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code == "intent_digest_mismatch"


def test_grant_when_expired_rejected(uow_factory: sessionmaker[Session]) -> None:
    scenario = _require_approval(_create(uow_factory))
    assert scenario.approval is not None
    expired_at = UtcTimestamp(value=datetime(2026, 8, 16, 19, 34, 30, tzinfo=UTC))
    granted = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=scenario.approval.approval_id,
        operation_id=scenario.operation.operation_id,
        operation_version=scenario.operation.version,
        intent_digest=scenario.operation.intent.intent_digest,
        policy_decision_id=scenario.approval.policy_decision_id,
        state=ApprovalState.APPROVED,
        requested_at=TS,
        expires_at=expired_at,
        decided_at=LATER,
        decided_by=APPROVER,
        reason="approved",
    )
    result = apply_committed(
        uow_factory,
        ApprovalGrant(
            kind=TransitionKind.APPROVAL_GRANT,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=APPROVER,
            correlation_id=None,
            reason_code="grant",
            transition_audit_event_id=scenario.ids.next(),
            approval=granted,
            approval_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code == "approval_expired"


def test_grant_happy_path_sets_ready_and_execute_outbox(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = _require_approval(_create(uow_factory))
    assert scenario.approval is not None
    granted = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=scenario.approval.approval_id,
        operation_id=scenario.operation.operation_id,
        operation_version=scenario.operation.version,
        intent_digest=scenario.operation.intent.intent_digest,
        policy_decision_id=scenario.approval.policy_decision_id,
        state=ApprovalState.APPROVED,
        requested_at=scenario.approval.requested_at,
        expires_at=None,
        decided_at=LATER,
        decided_by=APPROVER,
        reason="approved",
    )
    result = apply_committed(
        uow_factory,
        ApprovalGrant(
            kind=TransitionKind.APPROVAL_GRANT,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=APPROVER,
            correlation_id=None,
            reason_code="grant",
            transition_audit_event_id=scenario.ids.next(),
            approval=granted,
            approval_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.APPLIED
    assert result.operation is not None
    assert result.operation.state is OperationState.READY
    assert result.outbox_event is not None
    assert result.outbox_event.command is WorkCommand.EXECUTE
    assert result.outbox_event.state is OutboxState.PENDING


def test_reject_sets_denied_without_outbox(uow_factory: sessionmaker[Session]) -> None:
    scenario = _require_approval(_create(uow_factory))
    assert scenario.approval is not None
    rejected = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=scenario.approval.approval_id,
        operation_id=scenario.operation.operation_id,
        operation_version=scenario.operation.version,
        intent_digest=scenario.operation.intent.intent_digest,
        policy_decision_id=scenario.approval.policy_decision_id,
        state=ApprovalState.REJECTED,
        requested_at=scenario.approval.requested_at,
        expires_at=None,
        decided_at=LATER,
        decided_by=APPROVER,
        reason="no",
    )
    result = apply_committed(
        uow_factory,
        ApprovalReject(
            kind=TransitionKind.APPROVAL_REJECT,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=APPROVER,
            correlation_id=None,
            reason_code="reject",
            transition_audit_event_id=scenario.ids.next(),
            approval=rejected,
            approval_audit_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.APPLIED
    assert result.operation is not None
    assert result.operation.state is OperationState.DENIED
    assert result.outbox_event is None
    with unit_of_work(uow_factory) as uow:
        assert uow.outbox_events.list_pending_for_claim(10) == []
