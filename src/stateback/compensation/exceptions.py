"""Compensation exceptions. SimulatedCompensationCrash is BaseException so
adapters cannot swallow a crash raised after `compensate`/`verify` return."""

from __future__ import annotations

from stateback.compensation.faults import CompensationCrashPoint


class StatebackCompensationError(Exception):
    reason_code: str

    def __init__(self, reason_code: str, message: str) -> None:
        if not reason_code:
            raise ValueError("reason_code must be non-empty")
        if not message:
            raise ValueError("message must be non-empty")
        self.reason_code = reason_code
        super().__init__(message)


class SimulatedCompensationCrash(BaseException):
    point: CompensationCrashPoint

    def __init__(self, point: CompensationCrashPoint) -> None:
        self.point = point
        super().__init__(point.value)
