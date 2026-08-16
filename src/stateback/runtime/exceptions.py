"""Runtime exceptions. SimulatedCrash is BaseException so adapters cannot swallow it."""

from __future__ import annotations

from stateback.runtime.faults import RuntimeCrashPoint


class StatebackRuntimeError(Exception):
    reason_code: str

    def __init__(self, reason_code: str, message: str) -> None:
        if not reason_code:
            raise ValueError("reason_code must be non-empty")
        if not message:
            raise ValueError("message must be non-empty")
        self.reason_code = reason_code
        super().__init__(message)


class SimulatedCrash(BaseException):
    point: RuntimeCrashPoint

    def __init__(self, point: RuntimeCrashPoint) -> None:
        self.point = point
        super().__init__(point.value)
