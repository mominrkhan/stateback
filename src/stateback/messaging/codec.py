"""Canonical JSON encoding for compact v1 work messages."""

from __future__ import annotations

import json
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from hashlib import sha256

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.messaging import WorkMessageV1

MAX_WORK_MESSAGE_BYTES = 16 * 1024
MAX_QUARANTINE_DIAGNOSTIC_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class QuarantineDiagnostic:
    diagnostic_type: str
    delivery_count: int
    payload_sha256: str
    payload_size_bytes: int
    message: WorkMessageV1 | None
    replay_payload: bytes | None

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": "v1",
            "diagnostic_type": self.diagnostic_type,
            "delivery_count": self.delivery_count,
            "message_id": None
            if self.message is None
            else self.message.message_id.value,
            "outbox_event_id": (
                None if self.message is None else self.message.outbox_event_id.value
            ),
            "operation_id": (
                None if self.message is None else self.message.operation_id.value
            ),
            "command": None if self.message is None else self.message.command.value,
            "payload_sha256": self.payload_sha256,
            "payload_size_bytes": self.payload_size_bytes,
            "replay_available": self.replay_payload is not None,
        }


def encode_work_message(message: WorkMessageV1) -> bytes:
    return json.dumps(
        message.to_wire(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decode_work_message(payload: bytes) -> WorkMessageV1:
    if len(payload) > MAX_WORK_MESSAGE_BYTES:
        raise ContractValidationError(
            "oversize_work_message", "work message exceeds the supported size"
        )
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


def decode_quarantine_diagnostic(payload: bytes) -> QuarantineDiagnostic:
    if len(payload) > MAX_QUARANTINE_DIAGNOSTIC_BYTES:
        raise ContractValidationError(
            "oversize_quarantine_diagnostic",
            "quarantine diagnostic exceeds the supported size",
        )
    try:
        raw = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine diagnostic must be valid ASCII JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine diagnostic must be an object",
        )
    diagnostic_type = raw.get("diagnostic_type")
    expected_keys = (
        {
            "contract_version",
            "diagnostic_type",
            "delivery_count",
            "payload_sha256",
            "payload_size_bytes",
            "replay_payload_base64",
        }
        if diagnostic_type == "POISON_MESSAGE"
        else {
            "contract_version",
            "diagnostic_type",
            "delivery_count",
            "message_id",
            "outbox_event_id",
            "operation_id",
            "command",
            "payload_sha256",
            "payload_size_bytes",
            "replay_payload_base64",
        }
    )
    delivery_count = raw.get("delivery_count")
    payload_digest = raw.get("payload_sha256")
    payload_size = raw.get("payload_size_bytes")
    if (
        set(raw) != expected_keys
        or raw.get("contract_version") != "v1"
        or diagnostic_type not in {"POISON_MESSAGE", "DELIVERY_EXHAUSTED"}
        or not isinstance(delivery_count, int)
        or isinstance(delivery_count, bool)
        or delivery_count < 1
        or not isinstance(payload_digest, str)
        or len(payload_digest) != 64
        or any(character not in "0123456789abcdef" for character in payload_digest)
        or not isinstance(payload_size, int)
        or isinstance(payload_size, bool)
        or payload_size < 0
    ):
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine diagnostic fields are invalid",
        )
    replay_encoded = raw.get("replay_payload_base64")
    if diagnostic_type == "POISON_MESSAGE":
        if replay_encoded is not None:
            raise ContractValidationError(
                "malformed_quarantine_diagnostic",
                "poison diagnostics cannot contain replay payloads",
            )
        return QuarantineDiagnostic(
            diagnostic_type=diagnostic_type,
            delivery_count=delivery_count,
            payload_sha256=payload_digest,
            payload_size_bytes=payload_size,
            message=None,
            replay_payload=None,
        )
    if not isinstance(replay_encoded, str):
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "delivery diagnostics require a replay payload",
        )
    try:
        replay_payload = b64decode(replay_encoded, validate=True)
    except (ValueError, Base64Error) as exc:
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine replay payload is invalid",
        ) from exc
    if (
        len(replay_payload) != payload_size
        or sha256(replay_payload).hexdigest() != payload_digest
    ):
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine replay payload identity is inconsistent",
        )
    message = decode_work_message(replay_payload)
    if (
        raw.get("message_id") != message.message_id.value
        or raw.get("outbox_event_id") != message.outbox_event_id.value
        or raw.get("operation_id") != message.operation_id.value
        or raw.get("command") != message.command.value
    ):
        raise ContractValidationError(
            "malformed_quarantine_diagnostic",
            "quarantine replay metadata is inconsistent",
        )
    return QuarantineDiagnostic(
        diagnostic_type=diagnostic_type,
        delivery_count=delivery_count,
        payload_sha256=payload_digest,
        payload_size_bytes=payload_size,
        message=message,
        replay_payload=replay_payload,
    )
