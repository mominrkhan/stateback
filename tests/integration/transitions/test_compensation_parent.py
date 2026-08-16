from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import CompensationState, OperationState
from stateback.persistence.uow import unit_of_work
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    command_for,
    prepare_source,
)
from tests.unit.domain.fixtures import OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_start_compensation_from_succeeded_sets_parent_and_pending_record(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.SUCCEEDED_START_COMPENSATION)
    result = scenario.apply(
        command_for(scenario, TransitionKind.SUCCEEDED_START_COMPENSATION)
    )
    assert result.operation is not None
    assert result.operation.state is OperationState.COMPENSATING
    assert result.compensation is not None
    assert result.compensation.state is CompensationState.PENDING
    assert result.operation.compensation_id == result.compensation.compensation_id


def test_claim_compensation_execution_does_not_bump_operation_version(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.COMPENSATION_APPLIED)
    before = scenario.operation.version
    assert scenario.compensation is not None
    assert scenario.compensation.state is CompensationState.EXECUTING
    assert scenario.operation.version == before
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
        assert loaded is not None
        assert loaded.version == before
        assert loaded.state is OperationState.COMPENSATING


def test_compensation_applied_sets_parent_compensated_and_record_succeeded(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.COMPENSATION_APPLIED)
    result = scenario.apply(command_for(scenario, TransitionKind.COMPENSATION_APPLIED))
    assert result.operation is not None
    assert result.operation.state is OperationState.COMPENSATED
    assert result.compensation is not None
    assert result.compensation.state is CompensationState.SUCCEEDED


def test_compensation_does_not_delete_original_attempts(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.COMPENSATION_APPLIED)
    with unit_of_work(uow_factory) as uow:
        before = uow.attempts.list_for_operation(OP_ID)
        assert before
    scenario.apply(command_for(scenario, TransitionKind.COMPENSATION_APPLIED))
    with unit_of_work(uow_factory) as uow:
        after = uow.attempts.list_for_operation(OP_ID)
        assert [item.attempt_id for item in after] == [
            item.attempt_id for item in before
        ]


def test_compensation_escalate_does_not_rewrite_compensation_row(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.COMPENSATION_ESCALATE)
    assert scenario.compensation is not None
    before_state = scenario.compensation.state
    before_version = scenario.compensation.version
    result = scenario.apply(command_for(scenario, TransitionKind.COMPENSATION_ESCALATE))
    assert result.outcome is TransitionOutcome.APPLIED
    assert result.operation is not None
    assert result.operation.state is OperationState.MANUAL_INTERVENTION
    assert result.compensation is not None
    assert result.compensation.state is before_state
    assert result.compensation.version == before_version
