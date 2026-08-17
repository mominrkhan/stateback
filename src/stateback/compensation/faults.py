"""Crash injection points for compensation. Raised after commit or provider call."""

from __future__ import annotations

from enum import StrEnum


class CompensationCrashPoint(StrEnum):
    AFTER_START_COMMIT = "after_start_commit"
    AFTER_CLAIM_COMMIT = "after_claim_commit"
    AFTER_COMPENSATE_BEFORE_EVIDENCE = "after_compensate_before_evidence"
    AFTER_EVIDENCE_COMMIT = "after_evidence_commit"
    AFTER_VERIFY_START_COMMIT = "after_verify_start_commit"
    AFTER_VERIFY_BEFORE_RESULT = "after_verify_before_result"
    AFTER_VERIFY_RESULT_COMMIT = "after_verify_result_commit"


def maybe_crash(
    crash_after: CompensationCrashPoint | None, point: CompensationCrashPoint
) -> None:
    if crash_after is point:
        from stateback.compensation.exceptions import SimulatedCompensationCrash

        raise SimulatedCompensationCrash(point)
