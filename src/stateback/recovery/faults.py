"""Crash injection points for verification/reconciliation. Raised after commit or verify."""

from __future__ import annotations

from enum import StrEnum


class RecoveryCrashPoint(StrEnum):
    AFTER_START_COMMIT = "after_start_commit"
    AFTER_VERIFY_BEFORE_RESULT = "after_verify_before_result"
    AFTER_RESULT_COMMIT = "after_result_commit"


def maybe_crash(
    crash_after: RecoveryCrashPoint | None, point: RecoveryCrashPoint
) -> None:
    if crash_after is point:
        from stateback.recovery.exceptions import SimulatedRecoveryCrash

        raise SimulatedRecoveryCrash(point)
