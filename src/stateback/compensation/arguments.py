"""Compensation argument derivation and provider key helpers."""

from __future__ import annotations

from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import ArgumentsMode, IdempotencyMode
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonObject, JsonValue
from stateback.domain.operation import Operation


def build_compensation_arguments(operation: Operation) -> JsonValue:
    if operation.intent.arguments_mode is ArgumentsMode.REFERENCE:
        return JsonObject(items=(("arguments_ref", operation.intent.arguments_ref),))
    return operation.intent.arguments


def provider_compensation_key(
    *,
    descriptor: EffectDescriptor,
    compensation_id: OpaqueId,
) -> str | None:
    if descriptor.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
        return f"sb:v1:comp-key:{compensation_id.value}"
    return None
