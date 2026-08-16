"""EffectRef and PrincipalRef — `contracts/OPERATION_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import PrincipalType
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.wire import (
    optional_key,
    parse_enum,
    parse_optional_str,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_EFFECT_FIELDS = frozenset({"provider", "action", "version"})
_PRINCIPAL_FIELDS = frozenset({"type", "id", "display_name"})


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectRef:
    provider: str
    action: str
    version: str

    def to_wire(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "action": self.action,
            "version": self.version,
        }

    def canonical_material(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "action": self.action,
            "version": self.version,
        }

    @classmethod
    def from_wire(cls, raw: object) -> EffectRef:
        data = require_mapping(raw, type_name="EffectRef")
        reject_unknown_keys(data, _EFFECT_FIELDS, type_name="EffectRef")
        return cls(
            provider=parse_str(
                require_key(data, "provider", type_name="EffectRef"),
                field="EffectRef.provider",
            ),
            action=parse_str(
                require_key(data, "action", type_name="EffectRef"),
                field="EffectRef.action",
            ),
            version=parse_str(
                require_key(data, "version", type_name="EffectRef"),
                field="EffectRef.version",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PrincipalRef:
    type: PrincipalType
    id: str
    display_name: str | None

    def __post_init__(self) -> None:
        if self.id.strip() != self.id:
            raise ContractValidationError(
                "invalid_principal_id",
                "PrincipalRef.id must not have leading or trailing whitespace",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "type": self.type.value,
            "id": self.id,
            "display_name": self.display_name,
        }

    @classmethod
    def from_wire(cls, raw: object) -> PrincipalRef:
        data = require_mapping(raw, type_name="PrincipalRef")
        reject_unknown_keys(data, _PRINCIPAL_FIELDS, type_name="PrincipalRef")
        return cls(
            type=parse_enum(
                PrincipalType,
                require_key(data, "type", type_name="PrincipalRef"),
                field="PrincipalRef.type",
            ),
            id=parse_str(
                require_key(data, "id", type_name="PrincipalRef"),
                field="PrincipalRef.id",
            ),
            display_name=parse_optional_str(
                optional_key(data, "display_name"),
                field="PrincipalRef.display_name",
            ),
        )
