"""Runtime result types. Distinct from EffectOutcome and TransitionOutcome."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stateback.domain.capability import ExecutionEvidence
from stateback.domain.errors import NormalizedError
from stateback.domain.operation import Operation
from stateback.transitions.results import TransitionResult


class RuntimeDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IN_FLIGHT = "IN_FLIGHT"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"


@dataclass(frozen=True, slots=True, kw_only=True)
class RuntimeResult:
    disposition: RuntimeDisposition
    reason_code: str
    operation: Operation | None
    transition: TransitionResult | None
    evidence: ExecutionEvidence | None
    validation_error: NormalizedError | None


def make_result(
    disposition: RuntimeDisposition,
    reason_code: str,
    *,
    operation: Operation | None = None,
    transition: TransitionResult | None = None,
    evidence: ExecutionEvidence | None = None,
    validation_error: NormalizedError | None = None,
) -> RuntimeResult:
    return RuntimeResult(
        disposition=disposition,
        reason_code=reason_code,
        operation=operation,
        transition=transition,
        evidence=evidence,
        validation_error=validation_error,
    )
