from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    AttemptState,
    CompensationState,
    EffectOutcome,
    IdempotencyMode,
    OperationState,
    PolicyVerdict,
    VerificationTarget,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision, PolicyObligations
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest
from stateback.transitions.commands import (
    ApprovalGrant,
    CompensationApplied,
    CompensationEscalate,
    CompensationOutcomeFailed,
    PolicyAllow,
    RetryCompensationAfterVerification,
    UnknownEscalate,
    UnknownSafeRetry,
)
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind
from stateback.transitions.preconditions import (
    RelatedRecords,
    evaluate_preconditions,
    evaluate_retry_compensation_after_verification_preconditions,
)
from tests.unit.compensation.fixtures import (
    DESCRIPTOR,
    make_compensation,
    make_compensation_attempt,
    make_operation,
    make_verification_request,
    make_verification_result,
)
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
        idempotency_mode=DESCRIPTOR.idempotency_mode,
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


def _retry_compensation_command() -> RetryCompensationAfterVerification:
    next_attempt = replace(
        make_compensation_attempt(state=AttemptState.STARTED, outcome=None),
        compensation_attempt_id=OpaqueId(value="00000000-0000-4000-8000-00000000000b"),
        attempt_number=2,
    )
    return RetryCompensationAfterVerification(
        kind=CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION,
        operation_id=OP_ID,
        expected_operation_version=2,
        compensation_id=make_compensation().compensation_id,
        expected_compensation_version=2,
        verification_result=make_verification_result(outcome=EffectOutcome.NOT_APPLIED),
        attempt=next_attempt,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="safe_retry",
        attempt_audit_event_id=AUDIT_ID,
        verification_audit_event_id=AUDIT_ID,
        outbox_event_id=OUTBOX_ID,
    )


def test_compensation_retry_rejects_missing_persisted_verification() -> None:
    command = _retry_compensation_command()
    reason = evaluate_retry_compensation_after_verification_preconditions(
        command,
        operation=make_operation(state=OperationState.COMPENSATING),
        compensation=make_compensation(state=CompensationState.VERIFYING, version=2),
        existing_attempts=(make_compensation_attempt(outcome=EffectOutcome.UNKNOWN),),
        existing_verification=None,
    )
    assert reason == "verification_missing"


def test_compensation_retry_rejects_wrong_persisted_verification_target() -> None:
    command = _retry_compensation_command()
    request = replace(
        make_verification_request(), target=VerificationTarget.ORIGINAL_EFFECT
    )
    reason = evaluate_retry_compensation_after_verification_preconditions(
        command,
        operation=make_operation(state=OperationState.COMPENSATING),
        compensation=make_compensation(state=CompensationState.VERIFYING, version=2),
        existing_attempts=(make_compensation_attempt(outcome=EffectOutcome.UNKNOWN),),
        existing_verification=(request, None),
    )
    assert reason == "verification_outcome_mismatch"


def _verifying_operation() -> tuple[Operation, Compensation, CompensationAttempt]:
    compensation = make_compensation(state=CompensationState.VERIFYING, version=2)
    operation = replace(
        make_operation(state=OperationState.COMPENSATING),
        compensation_id=compensation.compensation_id,
    )
    loaded_attempt = make_compensation_attempt(outcome=EffectOutcome.UNKNOWN)
    return operation, compensation, loaded_attempt


def _compensation_verification_request() -> VerificationRequest:
    return replace(make_verification_request(), target=VerificationTarget.COMPENSATION)


def test_compensation_applied_rejects_missing_persisted_verification() -> None:
    operation, compensation, loaded_attempt = _verifying_operation()
    command = CompensationApplied(
        kind=TransitionKind.COMPENSATION_APPLIED,
        operation_id=operation.operation_id,
        expected_version=operation.version,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="verified_applied",
        transition_audit_event_id=AUDIT_ID,
        completed_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.APPLIED
        ),
        compensation_result_audit_event_id=AUDIT_ID,
        verification_result=make_verification_result(outcome=EffectOutcome.APPLIED),
    )
    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(
            compensation=compensation,
            loaded_compensation_attempt=loaded_attempt,
        ),
    )
    assert reason == "verification_missing"


def test_compensation_failed_rejects_conflicting_persisted_verification() -> None:
    operation, compensation, loaded_attempt = _verifying_operation()
    command = CompensationOutcomeFailed(
        kind=TransitionKind.COMPENSATION_OUTCOME_FAILED,
        operation_id=operation.operation_id,
        expected_version=operation.version,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="verified_not_applied",
        transition_audit_event_id=AUDIT_ID,
        completed_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.NOT_APPLIED
        ),
        compensation_result_audit_event_id=AUDIT_ID,
        verification_result=make_verification_result(outcome=EffectOutcome.NOT_APPLIED),
    )
    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(
            compensation=compensation,
            loaded_compensation_attempt=loaded_attempt,
            existing_compensation_verification=(
                _compensation_verification_request(),
                make_verification_result(outcome=EffectOutcome.APPLIED),
            ),
        ),
    )
    assert reason == "evidence_conflict"


def test_compensation_escalate_rejects_wrong_verification_attempt() -> None:
    operation, compensation, loaded_attempt = _verifying_operation()
    command = CompensationEscalate(
        kind=TransitionKind.COMPENSATION_ESCALATE,
        operation_id=operation.operation_id,
        expected_version=operation.version,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="verification_inconclusive",
        transition_audit_event_id=AUDIT_ID,
        manual_audit_event_id=AUDIT_ID,
        verification_result=make_verification_result(outcome=EffectOutcome.UNKNOWN),
    )
    wrong_request = replace(
        _compensation_verification_request(),
        target_attempt_id=OpaqueId(value="00000000-0000-4000-8000-00000000000c"),
    )
    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(
            compensation=compensation,
            loaded_compensation_attempt=loaded_attempt,
            existing_compensation_verification=(wrong_request, None),
        ),
    )
    assert reason == "attempt_missing"


def test_compensation_outcome_rejects_non_latest_attempt() -> None:
    compensation = make_compensation(state=CompensationState.EXECUTING, version=2)
    operation = replace(
        make_operation(state=OperationState.COMPENSATING),
        compensation_id=compensation.compensation_id,
    )
    older_completed = make_compensation_attempt(outcome=EffectOutcome.APPLIED)
    latest_started = replace(
        make_compensation_attempt(state=AttemptState.STARTED, outcome=None),
        compensation_attempt_id=OpaqueId(value="00000000-0000-4000-8000-00000000000d"),
        attempt_number=2,
    )
    command = CompensationApplied(
        kind=TransitionKind.COMPENSATION_APPLIED,
        operation_id=operation.operation_id,
        expected_version=operation.version,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="late_applied",
        transition_audit_event_id=AUDIT_ID,
        completed_compensation_attempt=older_completed,
        compensation_result_audit_event_id=AUDIT_ID,
    )

    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(
            compensation=compensation,
            compensation_attempts=(older_completed, latest_started),
            loaded_compensation_attempt=latest_started,
        ),
    )
    assert reason == "evidence_conflict"


def test_compensation_applied_rejects_not_applied_verification() -> None:
    operation, compensation, loaded_attempt = _verifying_operation()
    result = make_verification_result(outcome=EffectOutcome.NOT_APPLIED)
    command = CompensationApplied(
        kind=TransitionKind.COMPENSATION_APPLIED,
        operation_id=operation.operation_id,
        expected_version=operation.version,
        occurred_at=LATER,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="contradictory_applied",
        transition_audit_event_id=AUDIT_ID,
        completed_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.APPLIED
        ),
        compensation_result_audit_event_id=AUDIT_ID,
        verification_result=result,
    )

    reason = evaluate_preconditions(
        command,
        operation=operation,
        related=RelatedRecords(
            compensation=compensation,
            loaded_compensation_attempt=loaded_attempt,
            existing_compensation_verification=(
                _compensation_verification_request(),
                result,
            ),
        ),
    )
    assert reason == "verification_outcome_mismatch"
