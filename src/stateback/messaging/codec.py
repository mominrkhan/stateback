"""Canonical JSON encoding for compact v1 work messages."""

from __future__ import annotations

import json
from base64 import b64encode
from hashlib import sha256

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.messaging import WorkMessageV1


def encode_work_message(message: WorkMessageV1) -> bytes:
    return json.dumps(
        message.to_wire(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_work_message(payload: bytes) -> WorkMessageV1:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "malformed_work_message", "work message must be valid UTF-8 JSON"
        ) from exc
    return WorkMessageV1.from_wire(raw)


def encode_quarantine_diagnostic(payload: bytes, *, delivery_count: int) -> bytes:
    """Build a sanitized, replayable diagnostic for terminal work delivery.

    A valid v1 work message contains identifiers only, so retaining its canonical
    bytes permits controlled operator replay. Invalid input is never copied into
    diagnostics because it is untrusted and may contain credentials.
    """
    try:
        message = decode_work_message(payload)
    except ContractValidationError:
        diagnostic: dict[str, object] = {
            "contract_version": "v1",
            "diagnostic_type": "POISON_MESSAGE",
            "delivery_count": delivery_count,
            "payload_sha256": sha256(payload).hexdigest(),
            "payload_size_bytes": len(payload),
            "replay_payload_base64": None,
        }
    else:
        canonical_payload = encode_work_message(message)
        diagnostic = {
            "contract_version": "v1",
            "diagnostic_type": "DELIVERY_EXHAUSTED",
            "delivery_count": delivery_count,
            "message_id": message.message_id.value,
            "outbox_event_id": message.outbox_event_id.value,
            "operation_id": message.operation_id.value,
            "command": message.command.value,
            "payload_sha256": sha256(canonical_payload).hexdigest(),
            "payload_size_bytes": len(canonical_payload),
            "replay_payload_base64": b64encode(canonical_payload).decode("ascii"),
        }
    return json.dumps(
        diagnostic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
