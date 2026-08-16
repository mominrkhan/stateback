from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    IdempotencyMode,
    OperationState,
    PolicyVerdict,
)
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision, PolicyObligations
from stateback.domain.time import UtcTimestamp
from stateback.transitions.commands import (
    ApprovalGrant,
    PolicyAllow,
    UnknownEscalate,
    UnknownSafeRetry,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.preconditions import RelatedRecords, evaluate_preconditions
from tests.unit.domain.fixtures import (
    APPROVAL_ID,
    AUDIT_ID,
    LATER,
    OP_ID,
    OUTBOX_ID,
    POLICY_ID,
    REQUESTER,
    RISK,
    TS,
    make_intent,
)

pytestmark = pytest.mark.unit


def _operation(*, state: OperationState, version: int = 1) -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=state,
        version=version,
        intent=make_intent(),
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=POLICY_ID
        if state is not OperationState.PENDING_POLICY
        else None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS if version == 1 else LATER,
    )


def _policy(verdict: PolicyVerdict) -> PolicyDecision:
    return PolicyDecision(
        contract_version=CONTRACT_VERSION,
        policy_decision_id=POLICY_ID,
        operation_id=OP_ID,
        operation_version=1,
        intent_digest=make_intent().intent_digest,
        verdict=verdict,
        reason_codes=("test",),
        explanation=None,
        obligations=PolicyObligations(
            require_verification=False,
            max_automatic_execution_attempts=None,
            max_automatic_recovery_attempts=None,
            automatic_compensation_allowed=False,
            operator_reason_required=False,
            approval_expires_at=None,
        ),
        policy_revision="policy-v1",
        evaluated_at=TS,
    )


def test_policy_allow_rejects_deny_verdict() -> None:
    command = PolicyAllow(
        kind=TransitionKind.POLICY_ALLOW,
        operation_id=OP_ID,
        expected_version=1,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="test",
        transition_audit_event_id=AUDIT_ID,
        policy_decision=_policy(PolicyVerdict.DENY),
        policy_audit_event_id=AUDIT_ID,
        outbox_event_id=OUTBOX_ID,
    )
    reason = evaluate_preconditions(
        command,
        operation=_operation(state=OperationState.PENDING_POLICY),
        related=RelatedRecords(),
    )
    assert reason == "policy_verdict_mismatch"


def test_retry_timeout_only_rejected() -> None:
    command = UnknownSafeRetry(
        kind=TransitionKind.UNKNOWN_SAFE_RETRY,
        operation_id=OP_ID,
        expected_version=1,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="test",
        transition_audit_event_id=AUDIT_ID,
        idempotency_mode=IdempotencyMode.NONE,
        execution_outcome=None,
        verification_outcome=None,
        outbox_event_id=OUTBOX_ID,
        insufficient_signal="timeout_only",
    )
    reason = evaluate_preconditions(
        command,
        operation=_operation(state=OperationState.UNKNOWN),
        related=RelatedRecords(),
    )
    assert reason == "timeout_only"


def test_retry_provider_key_needs_proof_rejected() -> None:
    command = UnknownSafeRetry(
        kind=TransitionKind.UNKNOWN_SAFE_RETRY,
        operation_id=OP_ID,
        expected_version=1,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="test",
        transition_audit_event_id=AUDIT_ID,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        execution_outcome=None,
        verification_outcome=None,
        outbox_event_id=OUTBOX_ID,
    )
    reason = evaluate_preconditions(
        command,
        operation=_operation(state=OperationState.UNKNOWN),
        related=RelatedRecords(),
    )
    assert reason == "retry_needs_capability_proof"


def test_approval_expired_rejected() -> None:
    expired_at = UtcTimestamp(value=datetime(2026, 8, 16, 19, 34, 30, tzinfo=UTC))
    operation = _operation(state=OperationState.AWAITING_APPROVAL, version=2)
    approval = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=APPROVAL_ID,
        operation_id=OP_ID,
        operation_version=operation.version,
        intent_digest=operation.intent.intent_digest,
        policy_decision_id=POLICY_ID,
        state=ApprovalState.APPROVED,
        requested_at=TS,
        expires_at=expired_at,
        decided_at=LATER,
        decided_by=REQUESTER,
        reason="ok",
    )
    pending = Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=APPROVAL_ID,
        operation_id=OP_ID,
        operation_version=next_version(1),
        intent_digest=operation.intent.intent_digest,
        policy_decision_id=POLICY_ID,
        state=ApprovalState.PENDING,
        requested_at=TS,
        expires_at=expired_at,
        decided_at=None,
        decided_by=None,
        reason=None,
    )
    command = ApprovalGrant(
        kind=TransitionKind.APPROVAL_GRANT,
        approval=approval,
        approval_audit_event_id=AUDIT_ID,
        outbox_event_id=OUTBOX_ID,
        operation_id=OP_ID,
        expected_version=2,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="grant",
        transition_audit_event_id=AUDIT_ID,
    )
    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(existing_approval=pending),
    )
    assert reason == "approval_expired"


def test_actor_required_for_manual_escalate() -> None:
    command = UnknownEscalate(
        kind=TransitionKind.UNKNOWN_ESCALATE,
        manual_audit_event_id=AUDIT_ID,
        operation_id=OP_ID,
        expected_version=1,
        occurred_at=LATER,
        actor=None,
        correlation_id=None,
        reason_code="escalate",
        transition_audit_event_id=AUDIT_ID,
    )
    reason = evaluate_preconditions(
        command,
        operation=_operation(state=OperationState.UNKNOWN),
        related=RelatedRecords(),
    )
    assert reason == "actor_required"
