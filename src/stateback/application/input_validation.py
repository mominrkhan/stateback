"""Resource bounds for untrusted public and MCP input."""

from __future__ import annotations

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonValue, json_from_plain

MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 10_000
MAX_COLLECTION_ITEMS = 1_000
MAX_STRING_CHARACTERS = 65_536
MAX_METADATA_ENTRIES = 100
MAX_METADATA_KEY_CHARACTERS = 100
MAX_METADATA_VALUE_CHARACTERS = 1_000


def bounded_json_from_plain(value: object) -> JsonValue:
    """Convert untrusted JSON only after iterative size/depth validation."""

    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ContractValidationError(
                "input_too_large", "JSON input exceeds the supported shape"
            )
        if isinstance(current, str):
            if len(current) > MAX_STRING_CHARACTERS:
                raise ContractValidationError(
                    "input_too_large", "JSON string exceeds the supported length"
                )
        elif isinstance(current, list):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise ContractValidationError(
                    "input_too_large", "JSON array exceeds the supported length"
                )
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            if len(current) > MAX_COLLECTION_ITEMS:
                raise ContractValidationError(
                    "input_too_large", "JSON object exceeds the supported length"
                )
            for key, item in current.items():
                if isinstance(key, str) and len(key) > MAX_STRING_CHARACTERS:
                    raise ContractValidationError(
                        "input_too_large", "JSON key exceeds the supported length"
                    )
                stack.append((item, depth + 1))
    return json_from_plain(value)


def validate_metadata(items: tuple[tuple[str, str], ...]) -> None:
    if len(items) > MAX_METADATA_ENTRIES:
        raise ContractValidationError(
            "input_too_large", "metadata exceeds the supported entry count"
        )
    for key, value in items:
        if (
            len(key) > MAX_METADATA_KEY_CHARACTERS
            or len(value) > MAX_METADATA_VALUE_CHARACTERS
        ):
            raise ContractValidationError(
                "input_too_large", "metadata exceeds the supported field length"
            )
