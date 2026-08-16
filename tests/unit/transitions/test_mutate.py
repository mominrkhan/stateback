from __future__ import annotations

import pytest

from stateback.domain.enums import CONTRACT_VERSION, OperationState
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation
from stateback.transitions.mutate import replace_operation
from tests.unit.domain.fixtures import LATER, OP_ID, RISK, TS, make_intent

pytestmark = pytest.mark.unit


def _operation() -> Operation:
    intent = make_intent()
    return Operation(
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
        updated_at=TS,
    )


def test_replace_operation_preserves_intent_object() -> None:
    operation = _operation()
    replaced = replace_operation(
        operation,
        state=OperationState.READY,
        version=2,
        updated_at=LATER,
    )
    assert replaced.intent is operation.intent


def test_replace_operation_sets_state_and_version() -> None:
    operation = _operation()
    replaced = replace_operation(
        operation,
        state=OperationState.READY,
        version=2,
        updated_at=LATER,
    )
    assert replaced.state is OperationState.READY
    assert replaced.version == 2
    assert replaced.updated_at == LATER


def test_replace_does_not_change_operation_id() -> None:
    operation = _operation()
    replaced = replace_operation(
        operation,
        state=OperationState.READY,
        version=2,
        updated_at=LATER,
    )
    assert replaced.operation_id == operation.operation_id
    assert replaced.created_at == operation.created_at
    assert replaced.idempotency_identity == operation.idempotency_identity
    assert replaced.risk_level is operation.risk_level
    assert replaced.contract_version == operation.contract_version
