"""Injected clock protocol for the synchronous runtime."""

from __future__ import annotations

from typing import Protocol

from stateback.domain.time import UtcTimestamp


class Clock(Protocol):
    def now(self) -> UtcTimestamp: ...
