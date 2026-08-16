"""Opaque identifiers.

Encoding is a Phase 1 implementation decision. `contracts/README.md` leaves
concrete encoding unset; this file freezes lowercase 8-4-4-4-12 hex UUIDs.
Generation is injected by callers. Domain types never call `uuid.uuid4()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stateback.domain.exceptions import ContractValidationError

_OPAQUE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@dataclass(frozen=True, slots=True, kw_only=True, order=True)
class OpaqueId:
    value: str

    def __post_init__(self) -> None:
        if not _OPAQUE_ID_RE.fullmatch(self.value):
            raise ContractValidationError(
                "invalid_opaque_id",
                "opaque_id must be lowercase 8-4-4-4-12 hex",
            )

    def __str__(self) -> str:
        return self.value

    def to_wire(self) -> str:
        return self.value

    @classmethod
    def from_wire(cls, raw: object, *, field: str = "id") -> OpaqueId:
        if not isinstance(raw, str):
            raise ContractValidationError("invalid_type", f"{field} must be a string")
        return cls(value=raw)


def parse_optional_opaque_id(raw: object, *, field: str) -> OpaqueId | None:
    if raw is None:
        return None
    return OpaqueId.from_wire(raw, field=field)
