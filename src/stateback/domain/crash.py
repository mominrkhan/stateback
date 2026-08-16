"""Crash-boundary interpretation from `STATE_MACHINES.md` §13.

These functions classify durable records. They do not perform recovery I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    AttemptState,
    CrashInterpretation,
    OperationState,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CrashDecision:
    interpretation: CrashInterpretation
    reason_code: str


def interpret_execution_crash(
    *,
    operation_state: OperationState,
    attempt_state: AttemptState | None,
) -> CrashDecision:
    if operation_state is OperationState.READY:
        return CrashDecision(
            interpretation=CrashInterpretation.NO_PROVIDER_ATTEMPT,
            reason_code="ready_has_no_claimed_attempt",
        )
    if (
        operation_state is OperationState.EXECUTING
        and attempt_state is AttemptState.STARTED
    ):
        return CrashDecision(
            interpretation=CrashInterpretation.POTENTIALLY_UNKNOWN,
            reason_code="executing_started_may_have_crossed_provider",
        )
    if (
        operation_state is OperationState.EXECUTING
        and attempt_state is AttemptState.COMPLETED
    ):
        return CrashDecision(
            interpretation=CrashInterpretation.USE_DURABLE_EVIDENCE,
            reason_code="attempt_result_already_durable",
        )
    if attempt_state is AttemptState.COMPLETED:
        return CrashDecision(
            interpretation=CrashInterpretation.USE_DURABLE_EVIDENCE,
            reason_code="completed_attempt_has_outcome",
        )
    if operation_state is OperationState.EXECUTING and attempt_state is None:
        return CrashDecision(
            interpretation=CrashInterpretation.POTENTIALLY_UNKNOWN,
            reason_code="executing_without_attempt_is_inconsistent_treat_unknown",
        )
    return CrashDecision(
        interpretation=CrashInterpretation.USE_DURABLE_EVIDENCE,
        reason_code="reload_canonical_state",
    )
