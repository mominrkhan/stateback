"""JSON wire helpers for domain records."""

from __future__ import annotations

import json
from collections.abc import Callable

from stateback.domain.exceptions import ContractValidationError

_SEPARATORS = (",", ":")


def dumps_wire(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=_SEPARATORS,
        allow_nan=False,
        sort_keys=True,
    )


def loads_wire[T](text: str, from_wire: Callable[[object], T]) -> T:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractValidationError(
            "malformed_json",
            "payload is not valid JSON",
        ) from exc
    return from_wire(raw)
