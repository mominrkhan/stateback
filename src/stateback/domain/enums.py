"""Canonical v1 enums.

Symbol strings are owned by `STATE_MACHINES.md` and `contracts/`. Do not add
members without updating those owners first.
"""

from __future__ import annotations

from enum import StrEnum


class OperationState(StrEnum):
    PENDING_POLICY = "PENDING_POLICY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    COMPENSATING = "COMPENSATING"
    COMPENSATION_UNKNOWN = "COMPENSATION_UNKNOWN"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"


class EffectOutcome(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"
    UNKNOWN = "UNKNOWN"


class AttemptState(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PrincipalType(StrEnum):
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    SERVICE = "SERVICE"
    OPERATOR = "OPERATOR"


class ArgumentsMode(StrEnum):
    INLINE = "INLINE"
    REFERENCE = "REFERENCE"


class Mutability(StrEnum):
    READ_ONLY = "READ_ONLY"
    MUTATING = "MUTATING"


class IdempotencyMode(StrEnum):
    NONE = "NONE"
    NATURAL = "NATURAL"
    PROVIDER_KEY = "PROVIDER_KEY"


class VerificationMode(StrEnum):
    NONE = "NONE"
    READ_BACK = "READ_BACK"
    OPERATION_LOOKUP = "OPERATION_LOOKUP"
    CUSTOM = "CUSTOM"


class CompensationKind(StrEnum):
    NONE = "NONE"
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    MITIGATING = "MITIGATING"


class EvidenceSource(StrEnum):
    EXECUTION_RESPONSE = "EXECUTION_RESPONSE"
    OPERATION_LOOKUP = "OPERATION_LOOKUP"
    READ_BACK = "READ_BACK"
    CUSTOM = "CUSTOM"


class PolicyVerdict(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CompensationState(StrEnum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    UNKNOWN = "UNKNOWN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class VerificationState(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class OutboxState(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"


class WorkCommand(StrEnum):
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    COMPENSATE = "COMPENSATE"


class ErrorKind(StrEnum):
    VALIDATION = "VALIDATION"
    POLICY = "POLICY"
    AUTHENTICATION = "AUTHENTICATION"
    AUTHORIZATION = "AUTHORIZATION"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_TRANSPORT = "TRANSIENT_TRANSPORT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MALFORMED_PROVIDER_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
    PROVIDER_INCONSISTENT = "PROVIDER_INCONSISTENT"
    PERSISTENCE = "PERSISTENCE"
    MESSAGING = "MESSAGING"
    CONCURRENCY_CONFLICT = "CONCURRENCY_CONFLICT"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    UNSUPPORTED_CONTRACT_VERSION = "UNSUPPORTED_CONTRACT_VERSION"
    SECURITY = "SECURITY"
    INTERNAL = "INTERNAL"


class VerificationTarget(StrEnum):
    ORIGINAL_EFFECT = "ORIGINAL_EFFECT"
    COMPENSATION = "COMPENSATION"


class ReconciliationAction(StrEnum):
    MARK_SUCCEEDED = "MARK_SUCCEEDED"
    MARK_FAILED = "MARK_FAILED"
    MAKE_READY_FOR_SAFE_RETRY = "MAKE_READY_FOR_SAFE_RETRY"
    REMAIN_UNKNOWN = "REMAIN_UNKNOWN"
    REQUIRE_MANUAL_INTERVENTION = "REQUIRE_MANUAL_INTERVENTION"


class AuditEventType(StrEnum):
    OPERATION_CREATED = "operation.created.v1"
    POLICY_EVALUATED = "policy.evaluated.v1"
    APPROVAL_REQUESTED = "approval.requested.v1"
    APPROVAL_DECIDED = "approval.decided.v1"
    OPERATION_TRANSITIONED = "operation.transitioned.v1"
    EXECUTION_ATTEMPT_STARTED = "execution.attempt_started.v1"
    EXECUTION_EVIDENCE_RECORDED = "execution.evidence_recorded.v1"
    VERIFICATION_STARTED = "verification.started.v1"
    VERIFICATION_COMPLETED = "verification.completed.v1"
    RECONCILIATION_DECIDED = "reconciliation.decided.v1"
    COMPENSATION_REQUESTED = "compensation.requested.v1"
    COMPENSATION_ATTEMPTED = "compensation.attempted.v1"
    COMPENSATION_RESULT = "compensation.result.v1"
    OPERATOR_ACTION = "operator.action.v1"
    OUTBOX_DIAGNOSTIC = "outbox.diagnostic.v1"
    MANUAL_INTERVENTION_REASON = "manual_intervention.reason.v1"
    SECURITY_CONTROL_DECISION = "security.control_decision.v1"


class TransitionVerdict(StrEnum):
    LEGAL = "LEGAL"
    ILLEGAL = "ILLEGAL"


class RetrySafetyVerdict(StrEnum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    NEEDS_CAPABILITY_PROOF = "NEEDS_CAPABILITY_PROOF"


class RetrySafetyBasis(StrEnum):
    EXECUTION_NOT_APPLIED = "EXECUTION_NOT_APPLIED"
    VERIFIED_NOT_APPLIED = "VERIFIED_NOT_APPLIED"
    NATURAL_IDEMPOTENCY = "NATURAL_IDEMPOTENCY"
    PROVIDER_NATIVE_IDEMPOTENCY = "PROVIDER_NATIVE_IDEMPOTENCY"
    PROVIDER_SPECIFIC_CONTRACT = "PROVIDER_SPECIFIC_CONTRACT"


class CrashInterpretation(StrEnum):
    NO_PROVIDER_ATTEMPT = "NO_PROVIDER_ATTEMPT"
    POTENTIALLY_UNKNOWN = "POTENTIALLY_UNKNOWN"
    USE_DURABLE_EVIDENCE = "USE_DURABLE_EVIDENCE"


class ApprovalBindingVerdict(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


FORWARD_TERMINAL_STATES: frozenset[OperationState] = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.DENIED,
        OperationState.CANCELLED,
        OperationState.COMPENSATED,
        OperationState.COMPENSATION_FAILED,
        OperationState.MANUAL_INTERVENTION,
    }
)

ABSOLUTE_TERMINAL_STATES: frozenset[OperationState] = frozenset(
    {
        OperationState.DENIED,
        OperationState.CANCELLED,
        OperationState.COMPENSATED,
    }
)

CONTRACT_VERSION = "v1"
INITIAL_OPERATION_VERSION = 1
INITIAL_COMPENSATION_VERSION = 1
INITIAL_ATTEMPT_NUMBER = 1
INITIAL_AUDIT_SEQUENCE = 1
