from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.compensation import Compensation
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    AttemptState,
    CompensationKind,
    CompensationState,
    OperationState,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import compensation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.persistence.exceptions import DuplicateKeyError
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import (
    ATTEMPT_ID_2,
    make_compensation,
    make_compensation_attempt,
    make_operation,
    make_started_attempt,
)
from tests.unit.domain.fixtures import COMP_ATTEMPT_ID, COMP_ID, OP_ID, REQUESTER, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_insert_compensation_and_attempt(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation(state=OperationState.COMPENSATING))
        uow.compensations.insert(make_compensation())
        uow.compensation_attempts.insert(make_compensation_attempt())
    with unit_of_work(uow_factory) as uow:
        compensation = uow.compensations.get(COMP_ID)
        attempts = uow.compensation_attempts.list_for_compensation(COMP_ID)
    assert compensation is not None
    assert compensation.kind is CompensationKind.EXACT
    assert len(attempts) == 1
    assert attempts[0].state is AttemptState.STARTED
    assert attempts[0].compensation_attempt_id == COMP_ATTEMPT_ID


def test_kind_none_rejected() -> None:
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


def test_duplicate_compensation_attempt_number(
    uow_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.compensations.insert(make_compensation())
        uow.compensation_attempts.insert(make_compensation_attempt())
    with pytest.raises(DuplicateKeyError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.compensation_attempts.insert(
                make_compensation_attempt(compensation_attempt_id=ATTEMPT_ID_2)
            )
    assert exc.value.reason_code == "duplicate_compensation_attempt_number"


def test_original_operation_still_present(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.attempts.insert(make_started_attempt())
        uow.compensations.insert(make_compensation())
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
        attempts = uow.attempts.list_for_operation(OP_ID)
    assert loaded is not None
    assert loaded.intent == operation.intent
    assert len(attempts) == 1
    assert loaded.operation_id == OP_ID
