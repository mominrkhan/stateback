"""Strict JSON-object parsing helpers for v1 wire dictionaries."""

from __future__ import annotations

from enum import StrEnum

from stateback.domain.exceptions import ContractValidationError


def require_mapping(raw: object, *, type_name: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ContractValidationError(
            "invalid_type",
            f"{type_name} must be a JSON object",
        )
    for key in raw:
        if not isinstance(key, str):
            raise ContractValidationError(
                "invalid_type",
                f"{type_name} keys must be strings",
            )
    return raw


def reject_unknown_keys(
    data: dict[str, object],
    allowed: frozenset[str],
    *,
    type_name: str,
) -> None:
    extra = set(data) - allowed
    if extra:
        names = ", ".join(sorted(extra))
        raise ContractValidationError(
            "unknown_field",
            f"{type_name} has unknown field(s): {names}",
        )


def require_key(data: dict[str, object], key: str, *, type_name: str) -> object:
    if key not in data:
        raise ContractValidationError(
            "missing_field",
            f"{type_name}.{key} is required",
        )
    return data[key]


def optional_key(data: dict[str, object], key: str) -> object | None:
    if key not in data:
        return None
    return data[key]


def parse_str(raw: object, *, field: str) -> str:
    if not isinstance(raw, str):
        raise ContractValidationError("invalid_type", f"{field} must be a string")
    if raw == "":
        raise ContractValidationError("empty_string", f"{field} must be non-empty")
    return raw


def parse_optional_str(raw: object, *, field: str) -> str | None:
    if raw is None:
        return None
    return parse_str(raw, field=field)


def parse_bool(raw: object, *, field: str) -> bool:
    if not isinstance(raw, bool):
        raise ContractValidationError("invalid_type", f"{field} must be a boolean")
    return raw


def parse_optional_bool(raw: object, *, field: str) -> bool | None:
    if raw is None:
        return None
    return parse_bool(raw, field=field)


def parse_int(raw: object, *, field: str, minimum: int | None = None) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ContractValidationError("invalid_type", f"{field} must be an integer")
    if minimum is not None and raw < minimum:
        raise ContractValidationError(
            "invalid_range",
            f"{field} must be >= {minimum}",
        )
    return raw


def parse_optional_int(
    raw: object, *, field: str, minimum: int | None = None
) -> int | None:
    if raw is None:
        return None
    return parse_int(raw, field=field, minimum=minimum)


def parse_str_list(raw: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ContractValidationError("invalid_type", f"{field} must be an array")
    return tuple(
        parse_str(item, field=f"{field}[{index}]") for index, item in enumerate(raw)
    )


def parse_str_map(raw: object, *, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, dict):
        raise ContractValidationError("invalid_type", f"{field} must be an object")
    items: list[tuple[str, str]] = []
    for key, value in raw.items():
        if not isinstance(key, str) or key == "":
            raise ContractValidationError(
                "invalid_type",
                f"{field} keys must be non-empty strings",
            )
        items.append((key, parse_str(value, field=f"{field}.{key}")))
    items.sort(key=lambda pair: pair[0])
    keys = [key for key, _ in items]
    if len(keys) != len(set(keys)):
        raise ContractValidationError("duplicate_key", f"{field} has duplicate keys")
    return tuple(items)


def parse_enum[E: StrEnum](enum_cls: type[E], raw: object, *, field: str) -> E:
    if not isinstance(raw, str):
        raise ContractValidationError("invalid_type", f"{field} must be a string")
    try:
        return enum_cls(raw)
    except ValueError as exc:
        raise ContractValidationError(
            "unknown_enum",
            f"{field} has unknown value {raw!r}",
        ) from exc


def parse_optional_enum[E: StrEnum](
    enum_cls: type[E], raw: object, *, field: str
) -> E | None:
    if raw is None:
        return None
    return parse_enum(enum_cls, raw, field=field)


def parse_contract_version(raw: object, *, type_name: str) -> str:
    value = parse_str(raw, field=f"{type_name}.contract_version")
    if value != "v1":
        raise ContractValidationError(
            "unsupported_contract_version",
            f"{type_name}.contract_version {value!r} is not supported",
        )
    return value
