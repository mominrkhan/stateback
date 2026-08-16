from __future__ import annotations

import pytest

from stateback.domain.enums import CONTRACT_VERSION, ArgumentsMode, OperationState
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import (
    IntentEnvelope,
    operation_idempotency_identity,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.serde import dumps_wire, loads_wire
from stateback.domain.time import UtcTimestamp
from tests.unit.domain.fixtures import LATER, OP_ID, RISK, TS, make_intent

pytestmark = pytest.mark.unit


def test_invalid_calendar_timestamp_is_contract_error() -> None:
    with pytest.raises(ContractValidationError) as exc:
        UtcTimestamp.from_wire("2026-02-30T00:00:00.000000Z")
    assert exc.value.reason_code == "invalid_timestamp"


def test_inline_requires_arguments() -> None:
    with pytest.raises(ContractValidationError) as exc:
        IntentEnvelope.from_parts(
            effect=make_intent().effect,
            arguments_mode=ArgumentsMode.INLINE,
            arguments=None,
            arguments_ref=None,
            requester=make_intent().requester,
            requested_at=TS,
            metadata=(),
        )
    assert exc.value.reason_code == "illegal_combination"


def test_reference_forbids_inline_arguments() -> None:
    with pytest.raises(ContractValidationError) as exc:
        IntentEnvelope.from_parts(
            effect=make_intent().effect,
            arguments_mode=ArgumentsMode.REFERENCE,
            arguments=json_from_plain({"name": "demo"}),
            arguments_ref="arg://1",
            requester=make_intent().requester,
            requested_at=TS,
            metadata=(),
        )
    assert exc.value.reason_code == "illegal_combination"


def test_secret_metadata_rejected() -> None:
    with pytest.raises(ContractValidationError) as exc:
        make_intent(metadata=(("api_key", "k"),))
    assert exc.value.reason_code == "secret_field"


def test_operation_id_immutable_in_round_trip() -> None:
    intent = make_intent()
    operation = Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=OperationState.PENDING_POLICY,
        version=1,
        intent=intent,
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=LATER,
    )
    restored = loads_wire(dumps_wire(operation.to_wire()), Operation.from_wire)
    assert restored.operation_id == OP_ID
    assert restored.state is OperationState.PENDING_POLICY


def test_wrong_idempotency_identity_rejected() -> None:
    with pytest.raises(ContractValidationError) as exc:
        Operation(
            contract_version=CONTRACT_VERSION,
            operation_id=OP_ID,
            state=OperationState.PENDING_POLICY,
            version=1,
            intent=make_intent(),
            risk_level=RISK,
            idempotency_identity="other",
            current_policy_decision_id=None,
            current_approval_id=None,
            latest_attempt_id=None,
            latest_verification_id=None,
            compensation_id=None,
            created_at=TS,
            updated_at=TS,
        )
    assert exc.value.reason_code == "idempotency_mismatch"
