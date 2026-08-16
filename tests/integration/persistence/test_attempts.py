from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AttemptState, EffectOutcome, OperationState
from stateback.domain.exceptions import ContractValidationError
from stateback.persistence.exceptions import DuplicateKeyError, PersistenceError
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import (
    ATTEMPT_ID_2,
    make_completed_unknown_attempt,
    make_operation,
    make_started_attempt,
)
from tests.unit.domain.fixtures import ATTEMPT_ID, OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_insert_started_and_complete(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation(state=OperationState.EXECUTING))
        uow.attempts.insert(make_started_attempt())
    with unit_of_work(uow_factory) as uow:
        uow.attempts.complete(make_completed_unknown_attempt())
    with unit_of_work(uow_factory) as uow:
        loaded = uow.attempts.get(ATTEMPT_ID)
    assert loaded is not None
    assert loaded.state is AttemptState.COMPLETED
    assert loaded.outcome is EffectOutcome.UNKNOWN


def test_duplicate_attempt_number(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.attempts.insert(make_started_attempt())
    with pytest.raises(DuplicateKeyError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.attempts.insert(make_started_attempt(attempt_id=ATTEMPT_ID_2))
    assert exc.value.reason_code == "duplicate_attempt_number"


def test_complete_when_not_started(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    with pytest.raises(PersistenceError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.attempts.complete(make_completed_unknown_attempt())
    assert exc.value.reason_code == "attempt_not_started"
    with unit_of_work(uow_factory) as uow:
        uow.attempts.insert(make_started_attempt())
        uow.attempts.complete(make_completed_unknown_attempt())
    with pytest.raises(PersistenceError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.attempts.complete(make_completed_unknown_attempt())
    assert exc.value.reason_code == "attempt_not_started"


def test_started_cannot_store_outcome() -> None:
    from stateback.domain.attempt import ExecutionAttempt
    from stateback.domain.enums import CONTRACT_VERSION
    from tests.unit.domain.fixtures import TS

    with pytest.raises(ContractValidationError) as exc:
        ExecutionAttempt(
            contract_version=CONTRACT_VERSION,
            attempt_id=ATTEMPT_ID,
            operation_id=OP_ID,
            attempt_number=1,
            state=AttemptState.STARTED,
            started_at=TS,
            completed_at=None,
            provider_idempotency_key=None,
            external_operation_id=None,
            external_resource_ids=(),
            outcome=EffectOutcome.UNKNOWN,
            evidence=None,
            error=None,
            correlation_id=None,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_unknown_outcome_not_coerced_to_failed(
    uow_factory: sessionmaker[Session],
) -> None:
    operation = make_operation(state=OperationState.EXECUTING)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.attempts.insert(make_started_attempt())
        uow.attempts.complete(make_completed_unknown_attempt())
    with unit_of_work(uow_factory) as uow:
        loaded_attempt = uow.attempts.get(ATTEMPT_ID)
        loaded_operation = uow.operations.get(OP_ID)
    assert loaded_attempt is not None
    assert loaded_attempt.outcome is EffectOutcome.UNKNOWN
    assert loaded_operation is not None
    assert loaded_operation.state is OperationState.EXECUTING
