"""Recovery result types. Distinct from EffectOutcome and RuntimeDisposition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stateback.domain.capability import VerificationEvidence
from stateback.domain.operation import Operation
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.transitions.results import TransitionResult


class RecoveryDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryResult:
    disposition: RecoveryDisposition
    reason_code: str
    operation: Operation | None
    transition: TransitionResult | None
    verification_evidence: VerificationEvidence | None
    decision: ReconciliationDecision | None


def make_recovery_result(
    disposition: RecoveryDisposition,
    reason_code: str,
    *,
    operation: Operation | None = None,
    transition: TransitionResult | None = None,
    verification_evidence: VerificationEvidence | None = None,
    decision: ReconciliationDecision | None = None,
) -> RecoveryResult:
    return RecoveryResult(
        disposition=disposition,
        reason_code=reason_code,
        operation=operation,
        transition=transition,
        verification_evidence=verification_evidence,
        decision=decision,
    )
