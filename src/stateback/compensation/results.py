"""Compensation result types. Distinct from EffectOutcome and TransitionOutcome."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stateback.domain.capability import CompensationEvidence, VerificationEvidence
from stateback.domain.compensation import Compensation
from stateback.domain.operation import Operation
from stateback.transitions.results import TransitionResult


class CompensationDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IN_FLIGHT = "IN_FLIGHT"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationResult:
    disposition: CompensationDisposition
    reason_code: str
    operation: Operation | None
    compensation: Compensation | None
    transition: TransitionResult | None
    evidence: CompensationEvidence | None
    verification_evidence: VerificationEvidence | None


def make_compensation_result(
    disposition: CompensationDisposition,
    reason_code: str,
    *,
    operation: Operation | None = None,
    compensation: Compensation | None = None,
    transition: TransitionResult | None = None,
    evidence: CompensationEvidence | None = None,
    verification_evidence: VerificationEvidence | None = None,
) -> CompensationResult:
    return CompensationResult(
        disposition=disposition,
        reason_code=reason_code,
        operation=operation,
        compensation=compensation,
        transition=transition,
        evidence=evidence,
        verification_evidence=verification_evidence,
    )
