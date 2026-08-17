"""Pure precondition checks over already-loaded domain objects."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.approval_binding import evaluate_approval_binding
from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.crash import interpret_execution_crash
from stateback.domain.enums import (
    ApprovalBindingVerdict,
    ApprovalState,
    AttemptState,
    CompensationKind,
    CompensationState,
    CrashInterpretation,
    EffectOutcome,
    IdempotencyMode,
    OperationState,
    PolicyVerdict,
    ReconciliationAction,
    RetrySafetyVerdict,
    VerificationTarget,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision
from stateback.domain.retry_safety import evaluate_effect_retry_safety
from stateback.domain.time import UtcTimestamp
from stateback.domain.transitions import (
    compensation_parent_is_consistent,
    evaluate_compensation_transition,
)
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.transitions.commands import (
    ApprovalGrant,
    ApprovalReject,
    CancelAwaitingApproval,
    ClaimCompensationExecution,
    ClaimCompensationRetryAttempt,
    ClaimExecution,
    CompensationApplied,
    CompensationEscalate,
    CompensationFailedEscalate,
    CompensationFailedRetry,
    CompensationOutcomeFailed,
    CompensationOutcomeUnknown,
    CompensationUnknownApplied,
    CompensationUnknownEscalate,
    CompensationUnknownFailed,
    CompensationUnknownRetry,
    ExecutionApplied,
    ExecutionNotAppliedFail,
    ExecutionNotAppliedRetry,
    ExecutionRequireVerification,
    ExecutionUnknown,
    FailedStartCompensation,
    ManualSafeRetry,
    ManualStartCompensation,
    ManualStartVerification,
    OperationTransitionCommand,
    PolicyAllow,
    PolicyDeny,
    PolicyRequireApproval,
    RetryCompensationAfterVerification,
    StartCompensationVerification,
    SucceededStartCompensation,
    UnknownReconcileApplied,
    UnknownReconcileNotApplied,
    UnknownSafeRetry,
    UnknownStartVerification,
    VerificationApplied,
    VerificationEscalate,
    VerificationInconclusive,
    VerificationNotAppliedFail,
    VerificationNotAppliedRetry,
)
from stateback.transitions.kinds import (
    KIND_TO_EDGE,
    CompensationProgressKind,
    TransitionKind,
)
from stateback.transitions.outbox import OUTBOX_COMMAND_FOR_KIND

ACTOR_REQUIRED_KINDS = frozenset(
    {
        TransitionKind.CANCEL_PENDING_POLICY,
        TransitionKind.CANCEL_AWAITING_APPROVAL,
        TransitionKind.CANCEL_READY,
        TransitionKind.VERIFICATION_ESCALATE,
        TransitionKind.UNKNOWN_ESCALATE,
        TransitionKind.SUCCEEDED_START_COMPENSATION,
        TransitionKind.FAILED_START_COMPENSATION,
        TransitionKind.MANUAL_START_VERIFICATION,
        TransitionKind.MANUAL_START_COMPENSATION,
        TransitionKind.MANUAL_SAFE_RETRY,
        TransitionKind.COMPENSATION_ESCALATE,
        TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
        TransitionKind.COMPENSATION_FAILED_RETRY,
        TransitionKind.COMPENSATION_FAILED_ESCALATE,
        TransitionKind.APPROVAL_GRANT,
        TransitionKind.APPROVAL_REJECT,
    }
)

ESCALATE_KINDS = frozenset(
    {
        TransitionKind.COMPENSATION_ESCALATE,
        TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
        TransitionKind.COMPENSATION_FAILED_ESCALATE,
    }
)

COMPENSATION_TARGET_STATE: dict[TransitionKind, CompensationState] = {
    TransitionKind.COMPENSATION_APPLIED: CompensationState.SUCCEEDED,
    TransitionKind.COMPENSATION_OUTCOME_UNKNOWN: CompensationState.UNKNOWN,
    TransitionKind.COMPENSATION_OUTCOME_FAILED: CompensationState.FAILED,
    TransitionKind.COMPENSATION_UNKNOWN_RETRY: CompensationState.EXECUTING,
    TransitionKind.COMPENSATION_UNKNOWN_APPLIED: CompensationState.SUCCEEDED,
    TransitionKind.COMPENSATION_UNKNOWN_FAILED: CompensationState.FAILED,
    TransitionKind.COMPENSATION_FAILED_RETRY: CompensationState.EXECUTING,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class RelatedRecords:
    existing_approval: Approval | None = None
    attempts: tuple[ExecutionAttempt, ...] = ()
    loaded_attempt: ExecutionAttempt | None = None
    existing_verification_result: VerificationResult | None = None
    compensation: Compensation | None = None
    compensation_attempts: tuple[CompensationAttempt, ...] = ()
    loaded_compensation_attempt: CompensationAttempt | None = None
    existing_compensation_verification: (
        tuple[VerificationRequest, VerificationResult | None] | None
    ) = None


def map_retry_safety_reason(
    *,
    execution_outcome: EffectOutcome | None,
    verification_outcome: EffectOutcome | None,
    idempotency_mode: IdempotencyMode,
    insufficient_signal: str | None,
) -> str | None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=execution_outcome,
        verification_outcome=verification_outcome,
        idempotency_mode=idempotency_mode,
        insufficient_signal=insufficient_signal,
    )
    if decision.verdict is RetrySafetyVerdict.SAFE:
        return None
    if decision.verdict is RetrySafetyVerdict.NEEDS_CAPABILITY_PROOF:
        return "retry_needs_capability_proof"
    return decision.reason_code


def _check_actor(
    kind: TransitionKind,
    actor: object,
    *,
    approval: Approval | None,
    occurred_at: UtcTimestamp,
) -> str | None:
    required = kind in ACTOR_REQUIRED_KINDS
    if (
        kind is TransitionKind.CANCEL_AWAITING_APPROVAL
        and approval is not None
        and approval.state is ApprovalState.EXPIRED
        and approval.expires_at is not None
        and occurred_at.value >= approval.expires_at.value
    ):
        required = False
    if required and actor is None:
        return "actor_required"
    return None


def _check_policy(
    decision: PolicyDecision,
    operation: Operation,
    expected: PolicyVerdict,
) -> str | None:
    if decision.operation_id != operation.operation_id:
        return "policy_operation_mismatch"
    if decision.intent_digest != operation.intent.intent_digest:
        return "policy_digest_mismatch"
    if decision.operation_version != operation.version:
        return "policy_version_mismatch"
    if decision.verdict is not expected:
        return "policy_verdict_mismatch"
    return None


def _check_outbox_id(kind: TransitionKind, command: object) -> str | None:
    mapped = kind in OUTBOX_COMMAND_FOR_KIND
    has_id = getattr(command, "outbox_event_id", None) is not None
    if mapped and not has_id:
        return "outbox_id_required"
    if not mapped and has_id:
        return "outbox_id_forbidden"
    return None


def _check_execution_attempt_complete(
    *,
    operation: Operation,
    completed: ExecutionAttempt | None,
    loaded: ExecutionAttempt | None,
    expected_outcome: EffectOutcome | None,
    allow_unknown_crash: bool,
    occurred_at: UtcTimestamp,
) -> str | None:
    if operation.latest_attempt_id is None:
        return "attempt_missing"
    if loaded is None:
        return "attempt_missing"
    if loaded.operation_id != operation.operation_id:
        return "attempt_operation_mismatch"
    if completed is None:
        if not allow_unknown_crash:
            return "attempt_missing"
        if loaded.state is not AttemptState.STARTED:
            return "attempt_not_started"
        crash = interpret_execution_crash(
            operation_state=OperationState.EXECUTING,
            attempt_state=AttemptState.STARTED,
        )
        if crash.interpretation is not CrashInterpretation.POTENTIALLY_UNKNOWN:
            return "attempt_not_started"
        return None
    if completed.attempt_id != loaded.attempt_id:
        return "evidence_conflict"
    if completed.operation_id != operation.operation_id:
        return "attempt_operation_mismatch"
    if completed.attempt_number != loaded.attempt_number:
        return "attempt_number_mismatch"
    if loaded.state is AttemptState.COMPLETED:
        if completed.outcome != loaded.outcome:
            return "evidence_conflict"
        if expected_outcome is not None and loaded.outcome is not expected_outcome:
            return "attempt_outcome_mismatch"
        return None
    if loaded.state is not AttemptState.STARTED:
        return "attempt_not_started"
    if completed.state is not AttemptState.COMPLETED:
        return "attempt_not_completed"
    if completed.started_at != loaded.started_at:
        return "evidence_conflict"
    if expected_outcome is not None and completed.outcome is not expected_outcome:
        return "attempt_outcome_mismatch"
    return None


def _check_verification_complete(
    *,
    operation: Operation,
    result: VerificationResult,
    existing: VerificationResult | None,
    expected_outcome: EffectOutcome | None,
) -> str | None:
    if operation.latest_verification_id is None:
        return "verification_missing"
    if result.verification_id != operation.latest_verification_id:
        return "verification_missing"
    if expected_outcome is not None and result.outcome is not expected_outcome:
        return "verification_outcome_mismatch"
    if existing is not None:
        if existing.outcome is not result.outcome:
            return "evidence_conflict"
    return None


def _check_verification_request(
    request: VerificationRequest,
    operation: Operation,
    expected_version: int,
    *,
    expected_target: VerificationTarget = VerificationTarget.ORIGINAL_EFFECT,
) -> str | None:
    if request.operation_id != operation.operation_id:
        return "attempt_operation_mismatch"
    if request.target is not expected_target:
        return "verification_outcome_mismatch"
    if request.operation_version != expected_version:
        return "stale_version"
    return None


def _check_compensation_start(
    compensation: Compensation,
    operation: Operation,
) -> str | None:
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    if compensation.state is not CompensationState.PENDING:
        return "compensation_state_mismatch"
    if compensation.kind is CompensationKind.NONE:
        return "compensation_kind_none"
    parent = compensation_parent_is_consistent(
        CompensationState.PENDING,
        OperationState.COMPENSATING,
    )
    if not parent.is_legal():
        return "compensation_parent_inconsistent"
    return None


def _check_compensation_outcome(
    *,
    kind: TransitionKind,
    operation: Operation,
    compensation: Compensation | None,
    completed: CompensationAttempt | None,
    loaded_attempt: CompensationAttempt | None,
    expected_attempt_outcome: EffectOutcome | None,
    allow_missing_attempt: bool,
    verification_result: VerificationResult | None = None,
    expected_verification_outcome: EffectOutcome | None = None,
    existing_verification: (
        tuple[VerificationRequest, VerificationResult | None] | None
    ) = None,
) -> str | None:
    if operation.compensation_id is None:
        return "compensation_missing"
    if compensation is None:
        return "compensation_missing"
    if compensation.compensation_id != operation.compensation_id:
        return "compensation_parent_inconsistent"
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    current = compensation_parent_is_consistent(compensation.state, operation.state)
    if not current.is_legal():
        return "compensation_parent_inconsistent"
    if verification_result is not None:
        if (
            expected_verification_outcome is not None
            and verification_result.outcome is not expected_verification_outcome
        ):
            return "verification_outcome_mismatch"
        if existing_verification is None:
            return "verification_missing"
        request, durable_result = existing_verification
        if request.verification_id != verification_result.verification_id:
            return "verification_missing"
        if request.target is not VerificationTarget.COMPENSATION:
            return "verification_outcome_mismatch"
        if request.operation_id != operation.operation_id:
            return "attempt_operation_mismatch"
        if request.operation_version != operation.version:
            return "stale_version"
        if loaded_attempt is None:
            return "attempt_missing"
        if request.target_attempt_id != loaded_attempt.compensation_attempt_id:
            return "attempt_missing"
        if durable_result is not None and durable_result != verification_result:
            return "evidence_conflict"
    if kind not in ESCALATE_KINDS:
        target_comp = COMPENSATION_TARGET_STATE.get(kind)
        if target_comp is not None:
            target_parent = KIND_TO_EDGE[kind][1]
            target = compensation_parent_is_consistent(target_comp, target_parent)
            if not target.is_legal():
                return "compensation_parent_inconsistent"
            edge = evaluate_compensation_transition(compensation.state, target_comp)
            if not edge.is_legal() and compensation.state is not target_comp:
                return "compensation_state_mismatch"
    if completed is None:
        if not allow_missing_attempt:
            return "attempt_missing"
        return None
    if loaded_attempt is None:
        return "attempt_missing"
    if completed.compensation_id != compensation.compensation_id:
        return "evidence_conflict"
    if completed.compensation_attempt_id != loaded_attempt.compensation_attempt_id:
        return "evidence_conflict"
    if loaded_attempt.state is AttemptState.COMPLETED:
        if completed.outcome != loaded_attempt.outcome:
            return "evidence_conflict"
        if (
            expected_attempt_outcome is not None
            and loaded_attempt.outcome is not expected_attempt_outcome
        ):
            if (
                verification_result is not None
                and verification_result.outcome is expected_attempt_outcome
                and loaded_attempt.outcome is EffectOutcome.UNKNOWN
            ):
                return None
            return "attempt_outcome_mismatch"
        return None
    if loaded_attempt.state is not AttemptState.STARTED:
        return "attempt_not_started"
    if completed.state is not AttemptState.COMPLETED:
        return "attempt_not_completed"
    if (
        expected_attempt_outcome is not None
        and completed.outcome is not expected_attempt_outcome
    ):
        return "attempt_outcome_mismatch"
    return None


def evaluate_preconditions(
    command: OperationTransitionCommand,
    *,
    operation: Operation,
    related: RelatedRecords,
) -> str | None:
    kind = command.kind
    if not isinstance(kind, TransitionKind):
        return "unlisted_operation_transition"
    actor = getattr(command, "actor", None)
    occurred_at: UtcTimestamp = command.occurred_at
    approval = getattr(command, "approval", None)
    actor_reason = _check_actor(kind, actor, approval=approval, occurred_at=occurred_at)
    if actor_reason is not None:
        return actor_reason
    outbox_reason = _check_outbox_id(kind, command)
    if outbox_reason is not None:
        return outbox_reason

    if isinstance(command, PolicyAllow):
        return _check_policy(command.policy_decision, operation, PolicyVerdict.ALLOW)
    if isinstance(command, PolicyDeny):
        return _check_policy(command.policy_decision, operation, PolicyVerdict.DENY)
    if isinstance(command, PolicyRequireApproval):
        reason = _check_policy(
            command.policy_decision, operation, PolicyVerdict.REQUIRE_APPROVAL
        )
        if reason is not None:
            return reason
        approval_cmd = command.approval
        if approval_cmd.state is not ApprovalState.PENDING:
            return "approval_state_mismatch"
        if approval_cmd.operation_id != operation.operation_id:
            return "operation_id_mismatch"
        if approval_cmd.intent_digest != operation.intent.intent_digest:
            return "intent_digest_mismatch"
        if (
            approval_cmd.policy_decision_id
            != command.policy_decision.policy_decision_id
        ):
            return "policy_decision_mismatch"
        if approval_cmd.operation_version != next_version(operation.version):
            return "operation_version_mismatch"
        return None

    if isinstance(command, ApprovalGrant):
        if related.existing_approval is None:
            return "approval_missing"
        if related.existing_approval.state is not ApprovalState.PENDING:
            return "approval_state_mismatch"
        if command.approval.decided_by != command.actor:
            return "actor_required"
        binding = evaluate_approval_binding(
            approval=command.approval,
            operation=operation,
            now=occurred_at,
        )
        if binding.verdict is not ApprovalBindingVerdict.VALID:
            return binding.reason_code
        return None

    if isinstance(command, (ApprovalReject, CancelAwaitingApproval)):
        if related.existing_approval is None:
            return "approval_missing"
        if related.existing_approval.state is not ApprovalState.PENDING:
            return "approval_state_mismatch"
        if isinstance(command, ApprovalReject):
            if command.approval.state is not ApprovalState.REJECTED:
                return "approval_state_mismatch"
            if command.approval.decided_by != command.actor:
                return "actor_required"
        elif command.approval.state not in {
            ApprovalState.EXPIRED,
            ApprovalState.CANCELLED,
        }:
            return "approval_state_mismatch"
        if command.approval.decided_at is None:
            return "approval_state_mismatch"
        if command.approval.intent_digest != operation.intent.intent_digest:
            return "intent_digest_mismatch"
        return None

    if isinstance(command, ClaimExecution):
        if operation.current_policy_decision_id is None:
            return "policy_missing"
        attempt = command.attempt
        if attempt.operation_id != operation.operation_id:
            return "attempt_operation_mismatch"
        if attempt.state is not AttemptState.STARTED:
            return "attempt_not_started"
        if attempt.outcome is not None:
            return "attempt_outcome_mismatch"
        expected_number = len(related.attempts) + 1
        if attempt.attempt_number != expected_number:
            return "attempt_number_mismatch"
        if attempt.provider_idempotency_key is not None:
            for item in related.attempts:
                if (
                    item.provider_idempotency_key is not None
                    and item.provider_idempotency_key
                    != attempt.provider_idempotency_key
                ):
                    return "idempotency_key_mismatch"
        return None

    if isinstance(command, ExecutionApplied):
        return _check_execution_attempt_complete(
            operation=operation,
            completed=command.completed_attempt,
            loaded=related.loaded_attempt,
            expected_outcome=EffectOutcome.APPLIED,
            allow_unknown_crash=False,
            occurred_at=occurred_at,
        )
    if isinstance(command, ExecutionNotAppliedFail):
        return _check_execution_attempt_complete(
            operation=operation,
            completed=command.completed_attempt,
            loaded=related.loaded_attempt,
            expected_outcome=EffectOutcome.NOT_APPLIED,
            allow_unknown_crash=False,
            occurred_at=occurred_at,
        )
    if isinstance(command, ExecutionNotAppliedRetry):
        reason = _check_execution_attempt_complete(
            operation=operation,
            completed=command.completed_attempt,
            loaded=related.loaded_attempt,
            expected_outcome=EffectOutcome.NOT_APPLIED,
            allow_unknown_crash=False,
            occurred_at=occurred_at,
        )
        if reason is not None:
            return reason
        return map_retry_safety_reason(
            execution_outcome=EffectOutcome.NOT_APPLIED,
            verification_outcome=None,
            idempotency_mode=command.idempotency_mode,
            insufficient_signal=command.insufficient_signal,
        )
    if isinstance(command, ExecutionRequireVerification):
        reason = _check_execution_attempt_complete(
            operation=operation,
            completed=command.completed_attempt,
            loaded=related.loaded_attempt,
            expected_outcome=None,
            allow_unknown_crash=False,
            occurred_at=occurred_at,
        )
        if reason is not None:
            return reason
        return _check_verification_request(
            command.verification_request,
            operation,
            command.expected_version,
        )
    if isinstance(command, ExecutionUnknown):
        return _check_execution_attempt_complete(
            operation=operation,
            completed=command.completed_attempt,
            loaded=related.loaded_attempt,
            expected_outcome=EffectOutcome.UNKNOWN,
            allow_unknown_crash=True,
            occurred_at=occurred_at,
        )

    if isinstance(command, VerificationApplied):
        return _check_verification_complete(
            operation=operation,
            result=command.verification_result,
            existing=related.existing_verification_result,
            expected_outcome=EffectOutcome.APPLIED,
        )
    if isinstance(command, VerificationNotAppliedFail):
        return _check_verification_complete(
            operation=operation,
            result=command.verification_result,
            existing=related.existing_verification_result,
            expected_outcome=EffectOutcome.NOT_APPLIED,
        )
    if isinstance(command, VerificationInconclusive):
        return _check_verification_complete(
            operation=operation,
            result=command.verification_result,
            existing=related.existing_verification_result,
            expected_outcome=EffectOutcome.UNKNOWN,
        )
    if isinstance(command, VerificationNotAppliedRetry):
        reason = _check_verification_complete(
            operation=operation,
            result=command.verification_result,
            existing=related.existing_verification_result,
            expected_outcome=EffectOutcome.NOT_APPLIED,
        )
        if reason is not None:
            return reason
        return map_retry_safety_reason(
            execution_outcome=None,
            verification_outcome=EffectOutcome.NOT_APPLIED,
            idempotency_mode=command.idempotency_mode,
            insufficient_signal=command.insufficient_signal,
        )
    if isinstance(command, VerificationEscalate):
        if command.verification_result is None:
            return None
        return _check_verification_complete(
            operation=operation,
            result=command.verification_result,
            existing=related.existing_verification_result,
            expected_outcome=None,
        )

    if isinstance(command, (UnknownStartVerification, ManualStartVerification)):
        return _check_verification_request(
            command.verification_request,
            operation,
            command.expected_version,
        )

    if isinstance(command, UnknownSafeRetry):
        return map_retry_safety_reason(
            execution_outcome=command.execution_outcome,
            verification_outcome=command.verification_outcome,
            idempotency_mode=command.idempotency_mode,
            insufficient_signal=command.insufficient_signal,
        )
    if isinstance(command, ManualSafeRetry):
        return map_retry_safety_reason(
            execution_outcome=command.execution_outcome,
            verification_outcome=command.verification_outcome,
            idempotency_mode=command.idempotency_mode,
            insufficient_signal=command.insufficient_signal,
        )

    if isinstance(command, UnknownReconcileApplied):
        stored = command.reconciliation
        if stored.operation_id != operation.operation_id:
            return "attempt_operation_mismatch"
        if stored.operation_version != command.expected_version:
            return "stale_version"
        if stored.decision.action is not ReconciliationAction.MARK_SUCCEEDED:
            return "reconciliation_action_mismatch"
        return None
    if isinstance(command, UnknownReconcileNotApplied):
        stored = command.reconciliation
        if stored.operation_id != operation.operation_id:
            return "attempt_operation_mismatch"
        if stored.operation_version != command.expected_version:
            return "stale_version"
        if stored.decision.action is not ReconciliationAction.MARK_FAILED:
            return "reconciliation_action_mismatch"
        return None

    if isinstance(command, (SucceededStartCompensation, FailedStartCompensation)):
        return _check_compensation_start(command.compensation, operation)
    if isinstance(command, ManualStartCompensation):
        return _check_compensation_start(command.compensation, operation)

    if isinstance(command, CompensationApplied):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=command.completed_compensation_attempt,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=EffectOutcome.APPLIED,
            allow_missing_attempt=False,
            verification_result=command.verification_result,
            expected_verification_outcome=EffectOutcome.APPLIED,
            existing_verification=related.existing_compensation_verification,
        )
    if isinstance(command, CompensationOutcomeFailed):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=command.completed_compensation_attempt,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=EffectOutcome.NOT_APPLIED,
            allow_missing_attempt=False,
            verification_result=command.verification_result,
            expected_verification_outcome=EffectOutcome.NOT_APPLIED,
            existing_verification=related.existing_compensation_verification,
        )
    if isinstance(command, CompensationOutcomeUnknown):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=command.completed_compensation_attempt,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=EffectOutcome.UNKNOWN
            if command.completed_compensation_attempt is not None
            else None,
            allow_missing_attempt=True,
            verification_result=command.verification_result,
            expected_verification_outcome=EffectOutcome.UNKNOWN,
            existing_verification=related.existing_compensation_verification,
        )
    if isinstance(command, CompensationUnknownApplied):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=command.completed_compensation_attempt,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=EffectOutcome.APPLIED,
            allow_missing_attempt=False,
            verification_result=command.verification_result,
            expected_verification_outcome=EffectOutcome.APPLIED,
            existing_verification=related.existing_compensation_verification,
        )
    if isinstance(command, CompensationUnknownFailed):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=command.completed_compensation_attempt,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=EffectOutcome.NOT_APPLIED,
            allow_missing_attempt=False,
            verification_result=command.verification_result,
            expected_verification_outcome=EffectOutcome.NOT_APPLIED,
            existing_verification=related.existing_compensation_verification,
        )
    if isinstance(command, CompensationUnknownRetry):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=None,
            loaded_attempt=None,
            expected_attempt_outcome=None,
            allow_missing_attempt=True,
        )
    if isinstance(command, CompensationFailedRetry):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=None,
            loaded_attempt=None,
            expected_attempt_outcome=None,
            allow_missing_attempt=True,
        )
    if isinstance(
        command,
        (
            CompensationEscalate,
            CompensationUnknownEscalate,
            CompensationFailedEscalate,
        ),
    ):
        return _check_compensation_outcome(
            kind=kind,
            operation=operation,
            compensation=related.compensation,
            completed=None,
            loaded_attempt=related.loaded_compensation_attempt,
            expected_attempt_outcome=None,
            allow_missing_attempt=True,
            verification_result=getattr(command, "verification_result", None),
            existing_verification=related.existing_compensation_verification,
        )
    return None


def evaluate_claim_compensation_preconditions(
    command: ClaimCompensationExecution,
    *,
    operation: Operation,
    compensation: Compensation,
    existing_attempts: tuple[CompensationAttempt, ...],
) -> str | None:
    if command.kind is not CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION:
        return "unlisted_operation_transition"
    if operation.state is not OperationState.COMPENSATING:
        return "source_state_mismatch"
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    if compensation.state is not CompensationState.PENDING:
        return "compensation_state_mismatch"
    edge = evaluate_compensation_transition(
        CompensationState.PENDING, CompensationState.EXECUTING
    )
    if not edge.is_legal():
        return "unlisted_operation_transition"
    parent = compensation_parent_is_consistent(
        CompensationState.EXECUTING, OperationState.COMPENSATING
    )
    if not parent.is_legal():
        return "compensation_parent_inconsistent"
    attempt = command.attempt
    if attempt.compensation_id != compensation.compensation_id:
        return "compensation_parent_inconsistent"
    if attempt.state is not AttemptState.STARTED:
        return "attempt_not_started"
    if attempt.attempt_number != len(existing_attempts) + 1:
        return "attempt_number_mismatch"
    return None


def evaluate_start_compensation_verification_preconditions(
    command: StartCompensationVerification,
    *,
    operation: Operation,
    compensation: Compensation,
    loaded_attempt: CompensationAttempt | None,
) -> str | None:
    if command.kind is not CompensationProgressKind.START_COMPENSATION_VERIFICATION:
        return "unlisted_operation_transition"
    if operation.state is not OperationState.COMPENSATING:
        return "source_state_mismatch"
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    if compensation.state is not CompensationState.EXECUTING:
        return "compensation_state_mismatch"
    edge = evaluate_compensation_transition(
        CompensationState.EXECUTING, CompensationState.VERIFYING
    )
    if not edge.is_legal():
        return "unlisted_operation_transition"
    parent = compensation_parent_is_consistent(
        CompensationState.VERIFYING, OperationState.COMPENSATING
    )
    if not parent.is_legal():
        return "compensation_parent_inconsistent"
    reason = _check_verification_request(
        command.verification_request,
        operation,
        command.expected_operation_version,
        expected_target=VerificationTarget.COMPENSATION,
    )
    if reason is not None:
        return reason
    completed = command.completed_compensation_attempt
    if completed is not None:
        if loaded_attempt is None:
            return "attempt_missing"
        if completed.compensation_id != compensation.compensation_id:
            return "evidence_conflict"
        if completed.compensation_attempt_id != loaded_attempt.compensation_attempt_id:
            return "evidence_conflict"
        if loaded_attempt.state is AttemptState.COMPLETED:
            if completed.outcome != loaded_attempt.outcome:
                return "evidence_conflict"
            if loaded_attempt.outcome is not EffectOutcome.APPLIED:
                return "attempt_outcome_mismatch"
            return None
        if loaded_attempt.state is not AttemptState.STARTED:
            return "attempt_not_started"
        if completed.state is not AttemptState.COMPLETED:
            return "attempt_not_completed"
        if completed.outcome is not EffectOutcome.APPLIED:
            return "attempt_outcome_mismatch"
        return None
    if loaded_attempt is None:
        return "attempt_missing"
    if loaded_attempt.state not in (AttemptState.COMPLETED, AttemptState.STARTED):
        return "attempt_not_started"
    return None


def evaluate_claim_compensation_retry_attempt_preconditions(
    command: ClaimCompensationRetryAttempt,
    *,
    operation: Operation,
    compensation: Compensation,
    existing_attempts: tuple[CompensationAttempt, ...],
) -> str | None:
    if command.kind is not CompensationProgressKind.CLAIM_COMPENSATION_RETRY_ATTEMPT:
        return "unlisted_operation_transition"
    if operation.state is not OperationState.COMPENSATING:
        return "source_state_mismatch"
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    if compensation.state is not CompensationState.EXECUTING:
        return "compensation_state_mismatch"
    parent = compensation_parent_is_consistent(
        CompensationState.EXECUTING, OperationState.COMPENSATING
    )
    if not parent.is_legal():
        return "compensation_parent_inconsistent"
    if not existing_attempts:
        return "attempt_missing"
    latest = existing_attempts[-1]
    if latest.state is not AttemptState.COMPLETED:
        return "attempt_not_completed"
    attempt = command.attempt
    if attempt.compensation_id != compensation.compensation_id:
        return "compensation_parent_inconsistent"
    if attempt.state is not AttemptState.STARTED:
        return "attempt_not_started"
    if attempt.attempt_number != len(existing_attempts) + 1:
        return "attempt_number_mismatch"
    if attempt.provider_idempotency_key is not None:
        for item in existing_attempts:
            if (
                item.provider_idempotency_key is not None
                and item.provider_idempotency_key != attempt.provider_idempotency_key
            ):
                return "idempotency_key_mismatch"
    return None


def evaluate_retry_compensation_after_verification_preconditions(
    command: RetryCompensationAfterVerification,
    *,
    operation: Operation,
    compensation: Compensation,
    existing_attempts: tuple[CompensationAttempt, ...],
    existing_verification: tuple[VerificationRequest, VerificationResult | None] | None,
) -> str | None:
    if (
        command.kind
        is not CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION
    ):
        return "unlisted_operation_transition"
    if operation.state is not OperationState.COMPENSATING:
        return "source_state_mismatch"
    if compensation.original_operation_id != operation.operation_id:
        return "compensation_parent_inconsistent"
    if compensation.state is not CompensationState.VERIFYING:
        return "compensation_state_mismatch"
    edge = evaluate_compensation_transition(
        CompensationState.VERIFYING, CompensationState.EXECUTING
    )
    if not edge.is_legal():
        return "unlisted_operation_transition"
    parent = compensation_parent_is_consistent(
        CompensationState.EXECUTING, OperationState.COMPENSATING
    )
    if not parent.is_legal():
        return "compensation_parent_inconsistent"
    if command.verification_result.outcome is not EffectOutcome.NOT_APPLIED:
        return "verification_outcome_mismatch"
    if existing_verification is None:
        return "verification_missing"
    request, durable_result = existing_verification
    if request.verification_id != command.verification_result.verification_id:
        return "verification_missing"
    if request.target is not VerificationTarget.COMPENSATION:
        return "verification_outcome_mismatch"
    if request.operation_id != operation.operation_id:
        return "attempt_operation_mismatch"
    if request.operation_version != operation.version:
        return "stale_version"
    if not existing_attempts:
        return "attempt_missing"
    if request.target_attempt_id != existing_attempts[-1].compensation_attempt_id:
        return "attempt_missing"
    if durable_result is not None and durable_result != command.verification_result:
        return "evidence_conflict"
    attempt = command.attempt
    if attempt.compensation_id != compensation.compensation_id:
        return "compensation_parent_inconsistent"
    if attempt.state is not AttemptState.STARTED:
        return "attempt_not_started"
    if attempt.attempt_number != len(existing_attempts) + 1:
        return "attempt_number_mismatch"
    if attempt.provider_idempotency_key is not None:
        for item in existing_attempts:
            if (
                item.provider_idempotency_key is not None
                and item.provider_idempotency_key != attempt.provider_idempotency_key
            ):
                return "idempotency_key_mismatch"
    return map_retry_safety_reason(
        execution_outcome=None,
        verification_outcome=EffectOutcome.NOT_APPLIED,
        idempotency_mode=command.idempotency_mode,
        insufficient_signal=None,
    )


def approval_id_of(command: object) -> OpaqueId | None:
    approval = getattr(command, "approval", None)
    if not isinstance(approval, Approval):
        return None
    return approval.approval_id
