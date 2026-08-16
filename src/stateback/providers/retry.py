"""Replay-window parsing for provider-native idempotency keys."""

from __future__ import annotations

import re

from stateback.domain.capability import ProviderKeySemantics
from stateback.domain.time import UtcTimestamp

_POSITIVE_INT = re.compile(r"^[1-9][0-9]*$")


def parse_replay_window_seconds(raw: str | None) -> int | None:
    if raw is None:
        return None
    if _POSITIVE_INT.fullmatch(raw) is None:
        return None
    return int(raw)


def replay_window_has_elapsed(
    *,
    semantics: ProviderKeySemantics,
    started_at: UtcTimestamp,
    now: UtcTimestamp,
) -> bool:
    if semantics.replay_window is None:
        return False
    seconds = parse_replay_window_seconds(semantics.replay_window)
    if seconds is None:
        return True
    return (now.value - started_at.value).total_seconds() >= seconds
