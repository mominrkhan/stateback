"""IntentEnvelope — `contracts/OPERATION_CONTRACT.md` §4."""

from __future__ import annotations

import re
from dataclasses import dataclass

from stateback.domain.canonical import sha256_hex
from stateback.domain.enums import CONTRACT_VERSION, ArgumentsMode
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import (
    JsonObject,
    JsonValue,
    json_from_plain,
    json_to_plain,
    parse_optional_json_value,
)
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.domain.secrets import reject_secrets_in_json, reject_secrets_in_str_map
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_enum,
    parse_optional_str,
    parse_str,
    parse_str_map,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_FIELDS = frozenset(
    {
        "effect",
        "arguments_mode",
        "arguments",
        "arguments_ref",
        "canonical_arguments_hash",
        "intent_digest",
        "requester",
        "requested_at",
        "metadata",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def compute_canonical_arguments_hash(
    *,
    arguments_mode: ArgumentsMode,
    arguments: JsonValue | None,
    arguments_ref: str | None,
) -> str:
    material = JsonObject(
        items=(
            ("arguments", arguments if arguments is not None else None),
            ("arguments_mode", arguments_mode.value),
            ("arguments_ref", arguments_ref),
        )
    )
    return sha256_hex(material)


def compute_intent_digest(
    *,
    effect: EffectRef,
    arguments_mode: ArgumentsMode,
    arguments_ref: str | None,
    canonical_arguments_hash: str,
    requester: PrincipalRef,
    metadata: tuple[tuple[str, str], ...],
) -> str:
    ordered_metadata = tuple(sorted(metadata, key=lambda pair: pair[0]))
    metadata_obj = JsonObject(
        items=tuple((key, value) for key, value in ordered_metadata)
    )
    material = json_from_plain(
        {
            "arguments_mode": arguments_mode.value,
            "arguments_ref": arguments_ref,
            "canonical_arguments_hash": canonical_arguments_hash,
            "effect": effect.canonical_material(),
            "metadata": json_to_plain(metadata_obj),
            "requester": {"id": requester.id, "type": requester.type.value},
        }
    )
    return sha256_hex(material)


def operation_idempotency_identity(operation_id: OpaqueId) -> str:
    return f"sb:{CONTRACT_VERSION}:op:{operation_id.value}"


def compensation_idempotency_identity(compensation_id: OpaqueId) -> str:
    return f"sb:{CONTRACT_VERSION}:comp:{compensation_id.value}"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntentEnvelope:
    effect: EffectRef
    arguments_mode: ArgumentsMode
    arguments: JsonValue | None
    arguments_ref: str | None
    canonical_arguments_hash: str
    intent_digest: str
    requester: PrincipalRef
    requested_at: UtcTimestamp
    metadata: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.arguments_mode is ArgumentsMode.INLINE:
            if self.arguments is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "INLINE intent requires arguments",
                )
            if self.arguments_ref is not None:
                raise ContractValidationError(
                    "illegal_combination",
                    "INLINE intent forbids arguments_ref",
                )
            reject_secrets_in_json(self.arguments, field="IntentEnvelope.arguments")
        elif self.arguments_mode is ArgumentsMode.REFERENCE:
            if self.arguments is not None:
                raise ContractValidationError(
                    "illegal_combination",
                    "REFERENCE intent forbids inline arguments",
                )
            if self.arguments_ref is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "REFERENCE intent requires arguments_ref",
                )
        else:
            raise ContractValidationError(
                "unknown_enum",
                "unsupported arguments_mode",
            )
        reject_secrets_in_str_map(self.metadata, field="IntentEnvelope.metadata")
        if not _SHA256_RE.fullmatch(self.canonical_arguments_hash):
            raise ContractValidationError(
                "invalid_hash",
                "canonical_arguments_hash must be 64 lowercase hex chars",
            )
        if not _SHA256_RE.fullmatch(self.intent_digest):
            raise ContractValidationError(
                "invalid_hash",
                "intent_digest must be 64 lowercase hex chars",
            )
        expected_args = compute_canonical_arguments_hash(
            arguments_mode=self.arguments_mode,
            arguments=self.arguments,
            arguments_ref=self.arguments_ref,
        )
        if expected_args != self.canonical_arguments_hash:
            raise ContractValidationError(
                "hash_mismatch",
                "canonical_arguments_hash does not match canonical arguments",
            )
        expected_digest = compute_intent_digest(
            effect=self.effect,
            arguments_mode=self.arguments_mode,
            arguments_ref=self.arguments_ref,
            canonical_arguments_hash=self.canonical_arguments_hash,
            requester=self.requester,
            metadata=self.metadata,
        )
        if expected_digest != self.intent_digest:
            raise ContractValidationError(
                "hash_mismatch",
                "intent_digest does not match canonical material",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "effect": self.effect.to_wire(),
            "arguments_mode": self.arguments_mode.value,
            "arguments": (
                None if self.arguments is None else json_to_plain(self.arguments)
            ),
            "arguments_ref": self.arguments_ref,
            "canonical_arguments_hash": self.canonical_arguments_hash,
            "intent_digest": self.intent_digest,
            "requester": self.requester.to_wire(),
            "requested_at": self.requested_at.to_wire(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_parts(
        cls,
        *,
        effect: EffectRef,
        arguments_mode: ArgumentsMode,
        arguments: JsonValue | None,
        arguments_ref: str | None,
        requester: PrincipalRef,
        requested_at: UtcTimestamp,
        metadata: tuple[tuple[str, str], ...],
    ) -> IntentEnvelope:
        args_hash = compute_canonical_arguments_hash(
            arguments_mode=arguments_mode,
            arguments=arguments,
            arguments_ref=arguments_ref,
        )
        digest = compute_intent_digest(
            effect=effect,
            arguments_mode=arguments_mode,
            arguments_ref=arguments_ref,
            canonical_arguments_hash=args_hash,
            requester=requester,
            metadata=metadata,
        )
        return cls(
            effect=effect,
            arguments_mode=arguments_mode,
            arguments=arguments,
            arguments_ref=arguments_ref,
            canonical_arguments_hash=args_hash,
            intent_digest=digest,
            requester=requester,
            requested_at=requested_at,
            metadata=metadata,
        )

    @classmethod
    def from_wire(cls, raw: object) -> IntentEnvelope:
        data = require_mapping(raw, type_name="IntentEnvelope")
        reject_unknown_keys(data, _FIELDS, type_name="IntentEnvelope")
        return cls(
            effect=EffectRef.from_wire(
                require_key(data, "effect", type_name="IntentEnvelope")
            ),
            arguments_mode=parse_enum(
                ArgumentsMode,
                require_key(data, "arguments_mode", type_name="IntentEnvelope"),
                field="IntentEnvelope.arguments_mode",
            ),
            arguments=parse_optional_json_value(
                optional_key(data, "arguments"),
                field="IntentEnvelope.arguments",
            ),
            arguments_ref=parse_optional_str(
                optional_key(data, "arguments_ref"),
                field="IntentEnvelope.arguments_ref",
            ),
            canonical_arguments_hash=parse_str(
                require_key(
                    data, "canonical_arguments_hash", type_name="IntentEnvelope"
                ),
                field="IntentEnvelope.canonical_arguments_hash",
            ),
            intent_digest=parse_str(
                require_key(data, "intent_digest", type_name="IntentEnvelope"),
                field="IntentEnvelope.intent_digest",
            ),
            requester=PrincipalRef.from_wire(
                require_key(data, "requester", type_name="IntentEnvelope")
            ),
            requested_at=UtcTimestamp.from_wire(
                require_key(data, "requested_at", type_name="IntentEnvelope"),
                field="IntentEnvelope.requested_at",
            ),
            metadata=parse_str_map(
                require_key(data, "metadata", type_name="IntentEnvelope"),
                field="IntentEnvelope.metadata",
            ),
        )
