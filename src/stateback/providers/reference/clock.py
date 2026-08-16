"""Injected clock for the deterministic reference provider."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.time import UtcTimestamp


class Clock(Protocol):
    def now(self) -> UtcTimestamp: ...


class FixedClock:
    def __init__(self, current: UtcTimestamp) -> None:
        self._current = current

    def now(self) -> UtcTimestamp:
        return self._current

    def set(self, current: UtcTimestamp) -> None:
        self._current = current

    def advance(self, seconds: int) -> None:
        if seconds < 0:
            raise ContractValidationError(
                "invalid_range",
                "FixedClock.advance seconds must be >= 0",
            )
        self._current = UtcTimestamp(
            value=self._current.value + timedelta(seconds=seconds)
        )
