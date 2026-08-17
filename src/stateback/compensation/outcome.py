"""Pure mapping from compensate evidence to a COMPENSATION_* kind."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import EffectOutcome
from stateback.domain.policy import PolicyObligations
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensateKindDecision:
    kind: TransitionKind | CompensationProgressKind
    reason_code: str


def decide_compensate_kind(
    *,
    outcome: EffectOutcome,
    descriptor: EffectDescriptor,
    obligations: PolicyObligations,
) -> CompensateKindDecision:
    if outcome is EffectOutcome.UNKNOWN:
        return CompensateKindDecision(
            kind=TransitionKind.COMPENSATION_OUTCOME_UNKNOWN,
            reason_code="compensation_unknown",
        )
    if outcome is EffectOutcome.APPLIED:
        if (
            obligations.require_verification
            or not descriptor.immediate_response_can_prove_applied
        ):
            return CompensateKindDecision(
                kind=CompensationProgressKind.START_COMPENSATION_VERIFICATION,
                reason_code="compensation_require_verification",
            )
        return CompensateKindDecision(
            kind=TransitionKind.COMPENSATION_APPLIED,
            reason_code="compensation_applied",
        )
    return CompensateKindDecision(
        kind=TransitionKind.COMPENSATION_OUTCOME_FAILED,
        reason_code="compensation_not_applied_fail",
    )
