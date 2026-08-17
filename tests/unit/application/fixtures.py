from __future__ import annotations

from stateback.application.auth import AuthenticatedIdentity, Role
from stateback.domain.enums import CONTRACT_VERSION, OperationState, PrincipalType
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation
from stateback.domain.refs import PrincipalRef
from tests.unit.domain.fixtures import OP_ID, RISK, TS, make_intent

IDENTITY = AuthenticatedIdentity(
    principal=PrincipalRef(
        type=PrincipalType.AGENT, id="agent-1", display_name="Test Agent"
    ),
    roles=frozenset({Role.CALLER}),
)
OPERATOR = AuthenticatedIdentity(
    principal=PrincipalRef(
        type=PrincipalType.OPERATOR, id="operator-1", display_name="Test Operator"
    ),
    roles=frozenset({Role.READER, Role.OPERATOR, Role.APPROVER}),
)


def operation(state: OperationState = OperationState.READY) -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=state,
        version=2,
        intent=make_intent(),
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
