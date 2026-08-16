"""Crash injection points. Raised only after a successful commit (or after execute)."""

from __future__ import annotations

from enum import StrEnum


class RuntimeCrashPoint(StrEnum):
    AFTER_INTENT_COMMIT = "after_intent_commit"
    AFTER_POLICY_COMMIT = "after_policy_commit"
    AFTER_CLAIM_COMMIT = "after_claim_commit"
    AFTER_EXECUTE_BEFORE_EVIDENCE = "after_execute_before_evidence"
    AFTER_EVIDENCE_COMMIT = "after_evidence_commit"


def maybe_crash(
    crash_after: RuntimeCrashPoint | None, point: RuntimeCrashPoint
) -> None:
    if crash_after is point:
        from stateback.runtime.exceptions import SimulatedCrash

        raise SimulatedCrash(point)
