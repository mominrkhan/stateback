"""Canonical JSON values.

Floats, NaN, and Infinity are rejected. Changing this algorithm is a
compatibility change for `canonical_arguments_hash` and `intent_digest`.
"""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.exceptions import ContractValidationError

type JsonValue = None | bool | int | str | JsonArray | JsonObject


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonArray:
    items: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class JsonObject:
    items: tuple[tuple[str, JsonValue], ...]

    def __post_init__(self) -> None:
        keys = [key for key, _ in self.items]
        if any(key == "" for key in keys):
            raise ContractValidationError(
                "empty_string",
                "JSON object keys must be non-empty",
            )
        if len(keys) != len(set(keys)):
            raise ContractValidationError(
                "duplicate_key",
                "JSON object keys must be unique",
            )
        ordered = tuple(sorted(self.items, key=lambda pair: pair[0]))
        if ordered != self.items:
            raise ContractValidationError(
                "unsorted_keys",
                "JSON object keys must be sorted by Unicode code point",
            )

    def as_dict(self) -> dict[str, JsonValue]:
        return dict(self.items)


def json_from_plain(value: object) -> JsonValue:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        raise ContractValidationError(
            "non_canonical_number",
            "floats are not allowed in canonical JSON",
        )
    if isinstance(value, list):
        return JsonArray(items=tuple(json_from_plain(item) for item in value))
    if isinstance(value, dict):
        pairs: list[tuple[str, JsonValue]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError(
                    "invalid_type",
                    "JSON object keys must be strings",
                )
            pairs.append((key, json_from_plain(item)))
        pairs.sort(key=lambda pair: pair[0])
        return JsonObject(items=tuple(pairs))
    raise ContractValidationError(
        "invalid_type",
        f"unsupported JSON value type {type(value).__name__}",
    )


def json_to_plain(value: JsonValue) -> object:
    if isinstance(value, JsonArray):
        return [json_to_plain(item) for item in value.items]
    if isinstance(value, JsonObject):
        return {key: json_to_plain(item) for key, item in value.items}
    return value


def parse_json_value(raw: object, *, field: str) -> JsonValue:
    try:
        return json_from_plain(raw)
    except ContractValidationError as exc:
        raise ContractValidationError(exc.reason_code, f"{field}: {exc}") from exc


def parse_optional_json_value(raw: object, *, field: str) -> JsonValue | None:
    if raw is None:
        return None
    return parse_json_value(raw, field=field)
