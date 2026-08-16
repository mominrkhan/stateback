"""Named transition kinds, 1:1 with `STATE_MACHINES.md` §4."""

from __future__ import annotations

from enum import StrEnum

from stateback.domain.enums import OperationState


class TransitionKind(StrEnum):
    CREATE_OPERATION = "CREATE_OPERATION"
    POLICY_ALLOW = "POLICY_ALLOW"
    POLICY_REQUIRE_APPROVAL = "POLICY_REQUIRE_APPROVAL"
    POLICY_DENY = "POLICY_DENY"
    CANCEL_PENDING_POLICY = "CANCEL_PENDING_POLICY"
    APPROVAL_GRANT = "APPROVAL_GRANT"
    APPROVAL_REJECT = "APPROVAL_REJECT"
    CANCEL_AWAITING_APPROVAL = "CANCEL_AWAITING_APPROVAL"
    CLAIM_EXECUTION = "CLAIM_EXECUTION"
    CANCEL_READY = "CANCEL_READY"
    EXECUTION_APPLIED = "EXECUTION_APPLIED"
    EXECUTION_REQUIRE_VERIFICATION = "EXECUTION_REQUIRE_VERIFICATION"
    EXECUTION_NOT_APPLIED_RETRY = "EXECUTION_NOT_APPLIED_RETRY"
    EXECUTION_NOT_APPLIED_FAIL = "EXECUTION_NOT_APPLIED_FAIL"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    VERIFICATION_APPLIED = "VERIFICATION_APPLIED"
    VERIFICATION_NOT_APPLIED_RETRY = "VERIFICATION_NOT_APPLIED_RETRY"
    VERIFICATION_NOT_APPLIED_FAIL = "VERIFICATION_NOT_APPLIED_FAIL"
    VERIFICATION_INCONCLUSIVE = "VERIFICATION_INCONCLUSIVE"
    VERIFICATION_ESCALATE = "VERIFICATION_ESCALATE"
    UNKNOWN_START_VERIFICATION = "UNKNOWN_START_VERIFICATION"
    UNKNOWN_SAFE_RETRY = "UNKNOWN_SAFE_RETRY"
    UNKNOWN_RECONCILE_APPLIED = "UNKNOWN_RECONCILE_APPLIED"
    UNKNOWN_RECONCILE_NOT_APPLIED = "UNKNOWN_RECONCILE_NOT_APPLIED"
    UNKNOWN_ESCALATE = "UNKNOWN_ESCALATE"
    SUCCEEDED_START_COMPENSATION = "SUCCEEDED_START_COMPENSATION"
    FAILED_START_COMPENSATION = "FAILED_START_COMPENSATION"
    MANUAL_START_VERIFICATION = "MANUAL_START_VERIFICATION"
    MANUAL_START_COMPENSATION = "MANUAL_START_COMPENSATION"
    MANUAL_SAFE_RETRY = "MANUAL_SAFE_RETRY"
    COMPENSATION_APPLIED = "COMPENSATION_APPLIED"
    COMPENSATION_OUTCOME_UNKNOWN = "COMPENSATION_OUTCOME_UNKNOWN"
    COMPENSATION_OUTCOME_FAILED = "COMPENSATION_OUTCOME_FAILED"
    COMPENSATION_ESCALATE = "COMPENSATION_ESCALATE"
    COMPENSATION_UNKNOWN_RETRY = "COMPENSATION_UNKNOWN_RETRY"
    COMPENSATION_UNKNOWN_APPLIED = "COMPENSATION_UNKNOWN_APPLIED"
    COMPENSATION_UNKNOWN_FAILED = "COMPENSATION_UNKNOWN_FAILED"
    COMPENSATION_UNKNOWN_ESCALATE = "COMPENSATION_UNKNOWN_ESCALATE"
    COMPENSATION_FAILED_RETRY = "COMPENSATION_FAILED_RETRY"
    COMPENSATION_FAILED_ESCALATE = "COMPENSATION_FAILED_ESCALATE"


class CompensationProgressKind(StrEnum):
    CLAIM_COMPENSATION_EXECUTION = "CLAIM_COMPENSATION_EXECUTION"


KIND_TO_EDGE: dict[TransitionKind, tuple[OperationState | None, OperationState]] = {
    TransitionKind.CREATE_OPERATION: (None, OperationState.PENDING_POLICY),
    TransitionKind.POLICY_ALLOW: (
        OperationState.PENDING_POLICY,
        OperationState.READY,
    ),
    TransitionKind.POLICY_REQUIRE_APPROVAL: (
        OperationState.PENDING_POLICY,
        OperationState.AWAITING_APPROVAL,
    ),
    TransitionKind.POLICY_DENY: (
        OperationState.PENDING_POLICY,
        OperationState.DENIED,
    ),
    TransitionKind.CANCEL_PENDING_POLICY: (
        OperationState.PENDING_POLICY,
        OperationState.CANCELLED,
    ),
    TransitionKind.APPROVAL_GRANT: (
        OperationState.AWAITING_APPROVAL,
        OperationState.READY,
    ),
    TransitionKind.APPROVAL_REJECT: (
        OperationState.AWAITING_APPROVAL,
        OperationState.DENIED,
    ),
    TransitionKind.CANCEL_AWAITING_APPROVAL: (
        OperationState.AWAITING_APPROVAL,
        OperationState.CANCELLED,
    ),
    TransitionKind.CLAIM_EXECUTION: (
        OperationState.READY,
        OperationState.EXECUTING,
    ),
    TransitionKind.CANCEL_READY: (OperationState.READY, OperationState.CANCELLED),
    TransitionKind.EXECUTION_APPLIED: (
        OperationState.EXECUTING,
        OperationState.SUCCEEDED,
    ),
    TransitionKind.EXECUTION_REQUIRE_VERIFICATION: (
        OperationState.EXECUTING,
        OperationState.VERIFYING,
    ),
    TransitionKind.EXECUTION_NOT_APPLIED_RETRY: (
        OperationState.EXECUTING,
        OperationState.READY,
    ),
    TransitionKind.EXECUTION_NOT_APPLIED_FAIL: (
        OperationState.EXECUTING,
        OperationState.FAILED,
    ),
    TransitionKind.EXECUTION_UNKNOWN: (
        OperationState.EXECUTING,
        OperationState.UNKNOWN,
    ),
    TransitionKind.VERIFICATION_APPLIED: (
        OperationState.VERIFYING,
        OperationState.SUCCEEDED,
    ),
    TransitionKind.VERIFICATION_NOT_APPLIED_RETRY: (
        OperationState.VERIFYING,
        OperationState.READY,
    ),
    TransitionKind.VERIFICATION_NOT_APPLIED_FAIL: (
        OperationState.VERIFYING,
        OperationState.FAILED,
    ),
    TransitionKind.VERIFICATION_INCONCLUSIVE: (
        OperationState.VERIFYING,
        OperationState.UNKNOWN,
    ),
    TransitionKind.VERIFICATION_ESCALATE: (
        OperationState.VERIFYING,
        OperationState.MANUAL_INTERVENTION,
    ),
    TransitionKind.UNKNOWN_START_VERIFICATION: (
        OperationState.UNKNOWN,
        OperationState.VERIFYING,
    ),
    TransitionKind.UNKNOWN_SAFE_RETRY: (
        OperationState.UNKNOWN,
        OperationState.READY,
    ),
    TransitionKind.UNKNOWN_RECONCILE_APPLIED: (
        OperationState.UNKNOWN,
        OperationState.SUCCEEDED,
    ),
    TransitionKind.UNKNOWN_RECONCILE_NOT_APPLIED: (
        OperationState.UNKNOWN,
        OperationState.FAILED,
    ),
    TransitionKind.UNKNOWN_ESCALATE: (
        OperationState.UNKNOWN,
        OperationState.MANUAL_INTERVENTION,
    ),
    TransitionKind.SUCCEEDED_START_COMPENSATION: (
        OperationState.SUCCEEDED,
        OperationState.COMPENSATING,
    ),
    TransitionKind.FAILED_START_COMPENSATION: (
        OperationState.FAILED,
        OperationState.COMPENSATING,
    ),
    TransitionKind.MANUAL_START_VERIFICATION: (
        OperationState.MANUAL_INTERVENTION,
        OperationState.VERIFYING,
    ),
    TransitionKind.MANUAL_START_COMPENSATION: (
        OperationState.MANUAL_INTERVENTION,
        OperationState.COMPENSATING,
    ),
    TransitionKind.MANUAL_SAFE_RETRY: (
        OperationState.MANUAL_INTERVENTION,
        OperationState.READY,
    ),
    TransitionKind.COMPENSATION_APPLIED: (
        OperationState.COMPENSATING,
        OperationState.COMPENSATED,
    ),
    TransitionKind.COMPENSATION_OUTCOME_UNKNOWN: (
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_UNKNOWN,
    ),
    TransitionKind.COMPENSATION_OUTCOME_FAILED: (
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_FAILED,
    ),
    TransitionKind.COMPENSATION_ESCALATE: (
        OperationState.COMPENSATING,
        OperationState.MANUAL_INTERVENTION,
    ),
    TransitionKind.COMPENSATION_UNKNOWN_RETRY: (
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATING,
    ),
    TransitionKind.COMPENSATION_UNKNOWN_APPLIED: (
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATED,
    ),
    TransitionKind.COMPENSATION_UNKNOWN_FAILED: (
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATION_FAILED,
    ),
    TransitionKind.COMPENSATION_UNKNOWN_ESCALATE: (
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.MANUAL_INTERVENTION,
    ),
    TransitionKind.COMPENSATION_FAILED_RETRY: (
        OperationState.COMPENSATION_FAILED,
        OperationState.COMPENSATING,
    ),
    TransitionKind.COMPENSATION_FAILED_ESCALATE: (
        OperationState.COMPENSATION_FAILED,
        OperationState.MANUAL_INTERVENTION,
    ),
}
