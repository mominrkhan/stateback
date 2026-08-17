"""Injected clock protocol for the synchronous runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from stateback.domain.time import UtcTimestamp


class Clock(Protocol):
    def now(self) -> UtcTimestamp: ...


class SystemClock:
    """Production UTC clock; deterministic tests continue to inject fakes."""

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(value=datetime.now(UTC))
