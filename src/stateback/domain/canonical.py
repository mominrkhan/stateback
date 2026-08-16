"""Deterministic SHA-256 digests over canonical JSON.

This is a restricted canonicalization: floats are rejected, so RFC 8785
number formatting is not used. Changing this file is a compatibility change.
"""

from __future__ import annotations

import hashlib
import json

from stateback.domain.jsonutil import JsonValue, json_to_plain

_SEPARATORS = (",", ":")


def canonical_json_bytes(value: JsonValue) -> bytes:
    plain = json_to_plain(value)
    text = json.dumps(
        plain,
        ensure_ascii=False,
        separators=_SEPARATORS,
        allow_nan=False,
        sort_keys=True,
    )
    return text.encode("utf-8")


def sha256_hex(value: JsonValue) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
