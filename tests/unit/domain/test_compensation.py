from __future__ import annotations

import pytest

from stateback.domain.compensation import Compensation
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    CompensationKind,
    CompensationState,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import compensation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from tests.unit.domain.fixtures import COMP_ID, OP_ID, REQUESTER, TS

pytestmark = pytest.mark.unit


def test_none_kind_is_illegal() -> None:
    with pytest.raises(ContractValidationError) as exc:
        Compensation(
            contract_version=CONTRACT_VERSION,
            compensation_id=COMP_ID,
            original_operation_id=OP_ID,
            kind=CompensationKind.NONE,
            state=CompensationState.PENDING,
            version=1,
            intent_digest="a" * 64,
            arguments_mode=ArgumentsMode.INLINE,
            arguments=json_from_plain({"reason": "undo"}),
            arguments_ref=None,
            idempotency_identity=compensation_idempotency_identity(COMP_ID),
            requested_by=REQUESTER,
            policy_decision_id=None,
            created_at=TS,
            updated_at=TS,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_compensation_identity_distinct_from_operation() -> None:
    from stateback.domain.intent import operation_idempotency_identity

    assert compensation_idempotency_identity(COMP_ID) != operation_idempotency_identity(
        OP_ID
    )
    assert compensation_idempotency_identity(COMP_ID).startswith("sb:v1:comp:")
