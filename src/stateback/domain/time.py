"""UTC timestamps.

Serialized form is RFC 3339 / ISO-8601 with a `Z` suffix and exactly six
fractional digits: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from stateback.domain.exceptions import ContractValidationError

_WIRE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{6})Z$")


@dataclass(frozen=True, slots=True, kw_only=True, order=True)
class UtcTimestamp:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None:
            raise ContractValidationError(
                "naive_timestamp",
                "timestamp must be timezone-aware UTC",
            )
        offset = self.value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ContractValidationError(
                "non_utc_timestamp",
                "timestamp must have a zero UTC offset",
            )
        if self.value.microsecond < 0:
            raise ContractValidationError("invalid_timestamp", "invalid microsecond")

    def to_wire(self) -> str:
        return self.value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @classmethod
    def from_wire(cls, raw: object, *, field: str = "timestamp") -> UtcTimestamp:
        if not isinstance(raw, str):
            raise ContractValidationError("invalid_type", f"{field} must be a string")
        match = _WIRE_RE.fullmatch(raw)
        if match is None:
            raise ContractValidationError(
                "invalid_timestamp",
                f"{field} must be YYYY-MM-DDTHH:MM:SS.ffffffZ",
            )
        try:
            parsed = datetime.strptime(
                f"{match.group(1)}.{match.group(2)}",
                "%Y-%m-%dT%H:%M:%S.%f",
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise ContractValidationError(
                "invalid_timestamp",
                f"{field} must be YYYY-MM-DDTHH:MM:SS.ffffffZ",
            ) from exc
        return cls(value=parsed)
