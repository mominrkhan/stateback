from __future__ import annotations

import pytest

from stateback.domain.approval_binding import evaluate_approval_binding
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalBindingVerdict,
    ApprovalState,
    OperationState,
    PrincipalType,
)
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval
from stateback.domain.refs import PrincipalRef
from tests.unit.domain.fixtures import (
    APPROVAL_ID,
    LATER,
    OP_ID,
    POLICY_ID,
    RISK,
    TS,
    make_intent,
)

pytestmark = pytest.mark.unit


def _operation(*, state: OperationState) -> Operation:
    intent = make_intent()
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=state,
        version=1,
        intent=intent,
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=POLICY_ID,
        current_approval_id=APPROVAL_ID,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )


def _approval(
    *, digest: str, state: ApprovalState = ApprovalState.APPROVED
) -> Approval:
    return Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=APPROVAL_ID,
        operation_id=OP_ID,
        operation_version=1,
        intent_digest=digest,
        policy_decision_id=POLICY_ID,
        state=state,
        requested_at=TS,
        expires_at=LATER,
        decided_at=TS,
        decided_by=PrincipalRef(
            type=PrincipalType.HUMAN, id="approver-1", display_name=None
        ),
        reason="ok",
    )


def test_matching_approval_is_valid() -> None:
    operation = _operation(state=OperationState.AWAITING_APPROVAL)
    approval = _approval(digest=operation.intent.intent_digest)
    decision = evaluate_approval_binding(approval=approval, operation=operation, now=TS)
    assert decision.verdict is ApprovalBindingVerdict.VALID


def test_digest_mismatch_is_invalid() -> None:
    operation = _operation(state=OperationState.AWAITING_APPROVAL)
    approval = _approval(digest="0" * 64)
    decision = evaluate_approval_binding(approval=approval, operation=operation, now=TS)
    assert decision.verdict is ApprovalBindingVerdict.INVALID
    assert decision.reason_code == "intent_digest_mismatch"


def test_expired_approval_is_invalid() -> None:
    operation = _operation(state=OperationState.AWAITING_APPROVAL)
    approval = _approval(digest=operation.intent.intent_digest)
    decision = evaluate_approval_binding(
        approval=approval, operation=operation, now=LATER
    )
    assert decision.verdict is ApprovalBindingVerdict.INVALID
    assert decision.reason_code == "approval_expired"
