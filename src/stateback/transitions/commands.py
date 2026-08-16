"""Transition command dataclasses.

IDs and timestamps are caller-supplied. The service never fills omitted values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import EffectOutcome, IdempotencyMode
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval, PolicyDecision
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind

if TYPE_CHECKING:
    from stateback.persistence.types import StoredReconciliationDecision


@dataclass(frozen=True, slots=True, kw_only=True)
class _OperationCommand:
    kind: TransitionKind
    operation_id: OpaqueId
    expected_version: int
    occurred_at: UtcTimestamp
    actor: PrincipalRef | None
    correlation_id: str | None
    reason_code: str
    transition_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateOperation:
    kind: TransitionKind
    operation: Operation
    occurred_at: UtcTimestamp
    actor: PrincipalRef | None
    correlation_id: str | None
    reason_code: str
    created_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyAllow(_OperationCommand):
    policy_decision: PolicyDecision
    policy_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRequireApproval(_OperationCommand):
    policy_decision: PolicyDecision
    approval: Approval
    policy_audit_event_id: OpaqueId
    approval_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyDeny(_OperationCommand):
    policy_decision: PolicyDecision
    policy_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelPendingPolicy(_OperationCommand):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalGrant(_OperationCommand):
    approval: Approval
    approval_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalReject(_OperationCommand):
    approval: Approval
    approval_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelAwaitingApproval(_OperationCommand):
    approval: Approval


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimExecution(_OperationCommand):
    attempt: ExecutionAttempt
    attempt_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelReady(_OperationCommand):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionApplied(_OperationCommand):
    completed_attempt: ExecutionAttempt
    evidence_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRequireVerification(_OperationCommand):
    completed_attempt: ExecutionAttempt
    verification_request: VerificationRequest
    evidence_audit_event_id: OpaqueId
    verification_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionNotAppliedRetry(_OperationCommand):
    completed_attempt: ExecutionAttempt
    idempotency_mode: IdempotencyMode
    evidence_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId
    insufficient_signal: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionNotAppliedFail(_OperationCommand):
    completed_attempt: ExecutionAttempt
    evidence_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionUnknown(_OperationCommand):
    completed_attempt: ExecutionAttempt | None
    evidence_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationApplied(_OperationCommand):
    verification_result: VerificationResult
    verification_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationNotAppliedRetry(_OperationCommand):
    verification_result: VerificationResult
    idempotency_mode: IdempotencyMode
    verification_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId
    insufficient_signal: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationNotAppliedFail(_OperationCommand):
    verification_result: VerificationResult
    verification_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationInconclusive(_OperationCommand):
    verification_result: VerificationResult
    verification_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationEscalate(_OperationCommand):
    verification_result: VerificationResult | None
    manual_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownStartVerification(_OperationCommand):
    verification_request: VerificationRequest
    verification_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownSafeRetry(_OperationCommand):
    idempotency_mode: IdempotencyMode
    execution_outcome: EffectOutcome | None
    verification_outcome: EffectOutcome | None
    outbox_event_id: OpaqueId
    insufficient_signal: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownReconcileApplied(_OperationCommand):
    reconciliation: StoredReconciliationDecision
    reconciliation_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownReconcileNotApplied(_OperationCommand):
    reconciliation: StoredReconciliationDecision
    reconciliation_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownEscalate(_OperationCommand):
    manual_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class SucceededStartCompensation(_OperationCommand):
    compensation: Compensation
    compensation_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class FailedStartCompensation(_OperationCommand):
    compensation: Compensation
    compensation_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualStartVerification(_OperationCommand):
    verification_request: VerificationRequest
    operator_audit_event_id: OpaqueId
    verification_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualStartCompensation(_OperationCommand):
    compensation: Compensation
    operator_audit_event_id: OpaqueId
    compensation_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualSafeRetry(_OperationCommand):
    idempotency_mode: IdempotencyMode
    execution_outcome: EffectOutcome | None
    verification_outcome: EffectOutcome | None
    operator_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId
    insufficient_signal: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationApplied(_OperationCommand):
    completed_compensation_attempt: CompensationAttempt
    compensation_result_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationOutcomeUnknown(_OperationCommand):
    completed_compensation_attempt: CompensationAttempt | None
    compensation_result_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationOutcomeFailed(_OperationCommand):
    completed_compensation_attempt: CompensationAttempt
    compensation_result_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationEscalate(_OperationCommand):
    manual_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationUnknownRetry(_OperationCommand):
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationUnknownApplied(_OperationCommand):
    completed_compensation_attempt: CompensationAttempt


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationUnknownFailed(_OperationCommand):
    completed_compensation_attempt: CompensationAttempt


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationUnknownEscalate(_OperationCommand):
    manual_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationFailedRetry(_OperationCommand):
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationFailedEscalate(_OperationCommand):
    manual_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ClaimCompensationExecution:
    kind: CompensationProgressKind
    operation_id: OpaqueId
    expected_operation_version: int
    compensation_id: OpaqueId
    expected_compensation_version: int
    attempt: CompensationAttempt
    occurred_at: UtcTimestamp
    actor: PrincipalRef | None
    correlation_id: str | None
    reason_code: str
    attempt_audit_event_id: OpaqueId


OperationTransitionCommand = (
    CreateOperation
    | PolicyAllow
    | PolicyRequireApproval
    | PolicyDeny
    | CancelPendingPolicy
    | ApprovalGrant
    | ApprovalReject
    | CancelAwaitingApproval
    | ClaimExecution
    | CancelReady
    | ExecutionApplied
    | ExecutionRequireVerification
    | ExecutionNotAppliedRetry
    | ExecutionNotAppliedFail
    | ExecutionUnknown
    | VerificationApplied
    | VerificationNotAppliedRetry
    | VerificationNotAppliedFail
    | VerificationInconclusive
    | VerificationEscalate
    | UnknownStartVerification
    | UnknownSafeRetry
    | UnknownReconcileApplied
    | UnknownReconcileNotApplied
    | UnknownEscalate
    | SucceededStartCompensation
    | FailedStartCompensation
    | ManualStartVerification
    | ManualStartCompensation
    | ManualSafeRetry
    | CompensationApplied
    | CompensationOutcomeUnknown
    | CompensationOutcomeFailed
    | CompensationEscalate
    | CompensationUnknownRetry
    | CompensationUnknownApplied
    | CompensationUnknownFailed
    | CompensationUnknownEscalate
    | CompensationFailedRetry
    | CompensationFailedEscalate
)

CompensationProgressCommand = ClaimCompensationExecution

TransitionCommand = OperationTransitionCommand | CompensationProgressCommand

COMMAND_TYPE_TO_KIND: dict[type, TransitionKind | CompensationProgressKind] = {
    CreateOperation: TransitionKind.CREATE_OPERATION,
    PolicyAllow: TransitionKind.POLICY_ALLOW,
    PolicyRequireApproval: TransitionKind.POLICY_REQUIRE_APPROVAL,
    PolicyDeny: TransitionKind.POLICY_DENY,
    CancelPendingPolicy: TransitionKind.CANCEL_PENDING_POLICY,
    ApprovalGrant: TransitionKind.APPROVAL_GRANT,
    ApprovalReject: TransitionKind.APPROVAL_REJECT,
    CancelAwaitingApproval: TransitionKind.CANCEL_AWAITING_APPROVAL,
    ClaimExecution: TransitionKind.CLAIM_EXECUTION,
    CancelReady: TransitionKind.CANCEL_READY,
    ExecutionApplied: TransitionKind.EXECUTION_APPLIED,
    ExecutionRequireVerification: TransitionKind.EXECUTION_REQUIRE_VERIFICATION,
    ExecutionNotAppliedRetry: TransitionKind.EXECUTION_NOT_APPLIED_RETRY,
    ExecutionNotAppliedFail: TransitionKind.EXECUTION_NOT_APPLIED_FAIL,
    ExecutionUnknown: TransitionKind.EXECUTION_UNKNOWN,
    VerificationApplied: TransitionKind.VERIFICATION_APPLIED,
    VerificationNotAppliedRetry: TransitionKind.VERIFICATION_NOT_APPLIED_RETRY,
    VerificationNotAppliedFail: TransitionKind.VERIFICATION_NOT_APPLIED_FAIL,
    VerificationInconclusive: TransitionKind.VERIFICATION_INCONCLUSIVE,
    VerificationEscalate: TransitionKind.VERIFICATION_ESCALATE,
    UnknownStartVerification: TransitionKind.UNKNOWN_START_VERIFICATION,
    UnknownSafeRetry: TransitionKind.UNKNOWN_SAFE_RETRY,
    UnknownReconcileApplied: TransitionKind.UNKNOWN_RECONCILE_APPLIED,
    UnknownReconcileNotApplied: TransitionKind.UNKNOWN_RECONCILE_NOT_APPLIED,
    UnknownEscalate: TransitionKind.UNKNOWN_ESCALATE,
    SucceededStartCompensation: TransitionKind.SUCCEEDED_START_COMPENSATION,
    FailedStartCompensation: TransitionKind.FAILED_START_COMPENSATION,
    ManualStartVerification: TransitionKind.MANUAL_START_VERIFICATION,
    ManualStartCompensation: TransitionKind.MANUAL_START_COMPENSATION,
    ManualSafeRetry: TransitionKind.MANUAL_SAFE_RETRY,
    CompensationApplied: TransitionKind.COMPENSATION_APPLIED,
    CompensationOutcomeUnknown: TransitionKind.COMPENSATION_OUTCOME_UNKNOWN,
    CompensationOutcomeFailed: TransitionKind.COMPENSATION_OUTCOME_FAILED,
    CompensationEscalate: TransitionKind.COMPENSATION_ESCALATE,
    CompensationUnknownRetry: TransitionKind.COMPENSATION_UNKNOWN_RETRY,
    CompensationUnknownApplied: TransitionKind.COMPENSATION_UNKNOWN_APPLIED,
    CompensationUnknownFailed: TransitionKind.COMPENSATION_UNKNOWN_FAILED,
    CompensationUnknownEscalate: TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
    CompensationFailedRetry: TransitionKind.COMPENSATION_FAILED_RETRY,
    CompensationFailedEscalate: TransitionKind.COMPENSATION_FAILED_ESCALATE,
    ClaimCompensationExecution: CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION,
}
