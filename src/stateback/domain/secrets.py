"""Refuse secret-shaped keys and values in persistable domain payloads."""

from __future__ import annotations

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonArray, JsonObject, JsonValue

_FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "private_key",
    "access_key",
    "api_key",
    "authorization",
    "credential",
    "cookie",
)


def _normalize_key(key: str) -> str:
    return key.lower().replace("-", "_")


def key_is_forbidden(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS)


def value_is_forbidden(value: str) -> bool:
    stripped = value.strip()
    lower = stripped.lower()
    return lower.startswith("bearer ") or "-----begin " in lower


def reject_secrets_in_json(value: JsonValue, *, field: str) -> None:
    if isinstance(value, JsonArray):
        for index, item in enumerate(value.items):
            reject_secrets_in_json(item, field=f"{field}[{index}]")
        return
    if isinstance(value, JsonObject):
        for key, item in value.items:
            if key_is_forbidden(key):
                raise ContractValidationError(
                    "secret_field",
                    f"{field}.{key} looks like a secret key",
                )
            if isinstance(item, str) and value_is_forbidden(item):
                raise ContractValidationError(
                    "secret_field",
                    f"{field}.{key} looks like a secret value",
                )
            reject_secrets_in_json(item, field=f"{field}.{key}")
        return
    if isinstance(value, str) and value_is_forbidden(value):
        raise ContractValidationError(
            "secret_field",
            f"{field} looks like a secret value",
        )


def reject_secrets_in_str_map(
    items: tuple[tuple[str, str], ...], *, field: str
) -> None:
    for key, value in items:
        if key_is_forbidden(key):
            raise ContractValidationError(
                "secret_field",
                f"{field}.{key} looks like a secret key",
            )
        if value_is_forbidden(value):
            raise ContractValidationError(
                "secret_field",
                f"{field}.{key} looks like a secret value",
            )
