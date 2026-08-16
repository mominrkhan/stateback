from __future__ import annotations

from enum import StrEnum

import pytest

from stateback.domain.enums import (
    ApprovalState,
    ArgumentsMode,
    AttemptState,
    AuditEventType,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    IdempotencyMode,
    Mutability,
    OperationState,
    OutboxState,
    PolicyVerdict,
    PrincipalType,
    ReconciliationAction,
    RiskLevel,
    VerificationMode,
    VerificationState,
    VerificationTarget,
    WorkCommand,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.wire import parse_enum

pytestmark = pytest.mark.unit

_CASES: list[tuple[type[StrEnum], tuple[str, ...]]] = [
    (
        OperationState,
        (
            "PENDING_POLICY",
            "AWAITING_APPROVAL",
            "READY",
            "EXECUTING",
            "VERIFYING",
            "UNKNOWN",
            "SUCCEEDED",
            "FAILED",
            "DENIED",
            "CANCELLED",
            "COMPENSATING",
            "COMPENSATION_UNKNOWN",
            "COMPENSATED",
            "COMPENSATION_FAILED",
            "MANUAL_INTERVENTION",
        ),
    ),
    (EffectOutcome, ("APPLIED", "NOT_APPLIED", "UNKNOWN")),
    (AttemptState, ("STARTED", "COMPLETED")),
    (RiskLevel, ("LOW", "MODERATE", "HIGH", "CRITICAL")),
    (PrincipalType, ("AGENT", "HUMAN", "SERVICE", "OPERATOR")),
    (ArgumentsMode, ("INLINE", "REFERENCE")),
    (Mutability, ("READ_ONLY", "MUTATING")),
    (IdempotencyMode, ("NONE", "NATURAL", "PROVIDER_KEY")),
    (VerificationMode, ("NONE", "READ_BACK", "OPERATION_LOOKUP", "CUSTOM")),
    (CompensationKind, ("NONE", "EXACT", "APPROXIMATE", "MITIGATING")),
    (
        EvidenceSource,
        ("EXECUTION_RESPONSE", "OPERATION_LOOKUP", "READ_BACK", "CUSTOM"),
    ),
    (PolicyVerdict, ("ALLOW", "DENY", "REQUIRE_APPROVAL")),
    (ApprovalState, ("PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED")),
    (
        CompensationState,
        ("PENDING", "EXECUTING", "VERIFYING", "UNKNOWN", "SUCCEEDED", "FAILED"),
    ),
    (VerificationState, ("PENDING", "IN_PROGRESS", "COMPLETED")),
    (OutboxState, ("PENDING", "PUBLISHED")),
    (WorkCommand, ("EXECUTE", "VERIFY", "COMPENSATE")),
    (
        ErrorKind,
        (
            "VALIDATION",
            "POLICY",
            "AUTHENTICATION",
            "AUTHORIZATION",
            "PROVIDER_REJECTED",
            "RATE_LIMITED",
            "TRANSIENT_TRANSPORT",
            "PROVIDER_UNAVAILABLE",
            "MALFORMED_PROVIDER_RESPONSE",
            "PROVIDER_INCONSISTENT",
            "PERSISTENCE",
            "MESSAGING",
            "CONCURRENCY_CONFLICT",
            "UNSUPPORTED_CAPABILITY",
            "UNSUPPORTED_CONTRACT_VERSION",
            "SECURITY",
            "INTERNAL",
        ),
    ),
    (VerificationTarget, ("ORIGINAL_EFFECT", "COMPENSATION")),
    (
        ReconciliationAction,
        (
            "MARK_SUCCEEDED",
            "MARK_FAILED",
            "MAKE_READY_FOR_SAFE_RETRY",
            "REMAIN_UNKNOWN",
            "REQUIRE_MANUAL_INTERVENTION",
        ),
    ),
    (
        AuditEventType,
        (
            "operation.created.v1",
            "policy.evaluated.v1",
            "approval.requested.v1",
            "approval.decided.v1",
            "operation.transitioned.v1",
            "execution.attempt_started.v1",
            "execution.evidence_recorded.v1",
            "verification.started.v1",
            "verification.completed.v1",
            "reconciliation.decided.v1",
            "compensation.requested.v1",
            "compensation.attempted.v1",
            "compensation.result.v1",
            "operator.action.v1",
            "outbox.diagnostic.v1",
            "manual_intervention.reason.v1",
            "security.control_decision.v1",
        ),
    ),
]


@pytest.mark.parametrize(("enum_cls", "values"), _CASES)
def test_enum_members_match_canon(
    enum_cls: type[StrEnum], values: tuple[str, ...]
) -> None:
    assert tuple(member.value for member in enum_cls) == values
    if enum_cls is not AuditEventType:
        assert tuple(member.name for member in enum_cls) == values


@pytest.mark.parametrize("enum_cls", [item[0] for item in _CASES])
def test_unknown_enum_rejected(enum_cls: type[StrEnum]) -> None:
    with pytest.raises(ContractValidationError) as exc:
        parse_enum(enum_cls, "NOT_A_CANONICAL_VALUE", field="test")
    assert exc.value.reason_code == "unknown_enum"
