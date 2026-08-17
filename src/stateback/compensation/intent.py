"""Compensation intent digest. Reuses the domain canonicalization algorithm."""

from __future__ import annotations

from stateback.domain.canonical import sha256_hex
from stateback.domain.enums import CONTRACT_VERSION, ArgumentsMode, CompensationKind
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue, json_from_plain, json_to_plain


def compute_compensation_intent_digest(
    *,
    original_operation_id: OpaqueId,
    kind: CompensationKind,
    arguments_mode: ArgumentsMode,
    arguments: JsonValue | None,
    arguments_ref: str | None,
) -> str:
    material = json_from_plain(
        {
            "contract_version": CONTRACT_VERSION,
            "original_operation_id": original_operation_id.value,
            "kind": kind.value,
            "arguments_mode": arguments_mode.value,
            "arguments": None if arguments is None else json_to_plain(arguments),
            "arguments_ref": arguments_ref,
        }
    )
    return sha256_hex(material)
