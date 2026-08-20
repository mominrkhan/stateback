from __future__ import annotations

import base64
import json

import pytest

from stateback.domain.enums import CONTRACT_VERSION, WorkCommand
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import WorkMessageV1
from stateback.messaging.codec import (
    MAX_WORK_MESSAGE_BYTES,
    decode_quarantine_diagnostic,
    decode_work_message,
    encode_quarantine_diagnostic,
    encode_work_message,
)
from stateback.messaging.ids import DeterministicWorkIds
from tests.unit.domain.fixtures import TS


def oid(value: int) -> OpaqueId:
    return OpaqueId(value=f"00000000-0000-4000-8000-{value:012x}")


def message() -> WorkMessageV1:
    return WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=oid(1),
        outbox_event_id=oid(2),
        operation_id=oid(3),
        expected_operation_version=4,
        command=WorkCommand.EXECUTE,
        correlation_id="corr-1",
        created_at=TS,
    )


def test_codec_round_trip_is_canonical() -> None:
    encoded = encode_work_message(message())
    assert decode_work_message(encoded) == message()
    assert b'"arguments"' not in encoded
    assert encode_work_message(decode_work_message(encoded)) == encoded


@pytest.mark.parametrize(
    "payload",
    [b"not-json", b"\xff", b'{"contract_version":"v2"}'],
)
def test_decode_rejects_malformed_or_unsupported_message(payload: bytes) -> None:
    with pytest.raises(ContractValidationError):
        decode_work_message(payload)


def test_oversize_work_message_is_rejected_without_parsing() -> None:
    with pytest.raises(ContractValidationError, match="supported size"):
        decode_work_message(b"{" + b" " * MAX_WORK_MESSAGE_BYTES + b"}")


def test_redelivery_reuses_ids_and_new_outbox_changes_them() -> None:
    first = DeterministicWorkIds(message()).execute()
    duplicate = DeterministicWorkIds(message()).execute()
    changed = WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=oid(9),
        outbox_event_id=oid(10),
        operation_id=message().operation_id,
        expected_operation_version=5,
        command=WorkCommand.EXECUTE,
        correlation_id=None,
        created_at=TS,
    )
    later = DeterministicWorkIds(changed).execute()
    assert first == duplicate
    assert first.attempt_id != later.attempt_id


def test_valid_quarantine_diagnostic_is_identified_and_replayable() -> None:
    payload = encode_work_message(message())
    encoded = encode_quarantine_diagnostic(payload, delivery_count=4)
    diagnostic = json.loads(encoded.decode("utf-8"))
    assert diagnostic["diagnostic_type"] == "DELIVERY_EXHAUSTED"
    assert diagnostic["operation_id"] == message().operation_id.value
    assert base64.b64decode(diagnostic["replay_payload_base64"]) == payload
    decoded = decode_quarantine_diagnostic(encoded)
    assert decoded.message == message()
    assert decoded.replay_payload == payload


def test_poison_quarantine_diagnostic_does_not_copy_untrusted_payload() -> None:
    payload = b'{"token":"github_pat_must_not_escape"}'
    encoded = encode_quarantine_diagnostic(payload, delivery_count=1)
    diagnostic = json.loads(encoded.decode("utf-8"))
    assert diagnostic["diagnostic_type"] == "POISON_MESSAGE"
    assert diagnostic["replay_payload_base64"] is None
    assert diagnostic["payload_size_bytes"] == len(payload)
    assert b"must_not_escape" not in encoded
    assert decode_quarantine_diagnostic(encoded).replay_payload is None


def test_quarantine_decoder_rejects_tampered_replay_identity() -> None:
    diagnostic = json.loads(
        encode_quarantine_diagnostic(
            encode_work_message(message()), delivery_count=4
        ).decode("ascii")
    )
    diagnostic["operation_id"] = oid(99).value
    with pytest.raises(ContractValidationError, match="inconsistent"):
        decode_quarantine_diagnostic(
            json.dumps(diagnostic, sort_keys=True, separators=(",", ":")).encode()
        )
