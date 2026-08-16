"""Pure mapping from execute evidence to an EXECUTION_* kind."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import EffectOutcome, RetrySafetyVerdict
from stateback.domain.policy import PolicyObligations
from stateback.transitions.kinds import TransitionKind


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionKindDecision:
    kind: TransitionKind
    reason_code: str


def max_automatic_attempts(obligations: PolicyObligations) -> int:
    value = obligations.max_automatic_execution_attempts
    if value is None or value < 1:
        return 1
    return value


def decide_execution_kind(
    *,
    outcome: EffectOutcome,
    descriptor: EffectDescriptor,
    obligations: PolicyObligations,
    attempt_number: int,
    retry_verdict: RetrySafetyVerdict,
) -> ExecutionKindDecision:
    if outcome is EffectOutcome.UNKNOWN:
        return ExecutionKindDecision(
            kind=TransitionKind.EXECUTION_UNKNOWN,
            reason_code="execution_unknown",
        )
    if outcome is EffectOutcome.APPLIED:
        if (
            obligations.require_verification
            or not descriptor.immediate_response_can_prove_applied
        ):
            return ExecutionKindDecision(
                kind=TransitionKind.EXECUTION_REQUIRE_VERIFICATION,
                reason_code="execution_require_verification",
            )
        return ExecutionKindDecision(
            kind=TransitionKind.EXECUTION_APPLIED,
            reason_code="execution_applied",
        )
    if (
        retry_verdict is RetrySafetyVerdict.SAFE
        and attempt_number < max_automatic_attempts(obligations)
    ):
        return ExecutionKindDecision(
            kind=TransitionKind.EXECUTION_NOT_APPLIED_RETRY,
            reason_code="execution_not_applied_retry",
        )
    return ExecutionKindDecision(
        kind=TransitionKind.EXECUTION_NOT_APPLIED_FAIL,
        reason_code="execution_not_applied_fail",
    )
