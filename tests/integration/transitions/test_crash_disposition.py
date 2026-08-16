from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AttemptState, OperationState
from stateback.persistence.uow import unit_of_work
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    apply_committed,
    command_for,
    prefix_ready,
    prepare_source,
)
from tests.unit.domain.fixtures import OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_execution_unknown_with_started_attempt_does_not_complete_attempt(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.EXECUTION_UNKNOWN)
    result = scenario.apply(command_for(scenario, TransitionKind.EXECUTION_UNKNOWN))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
    assert result.outbox_event is not None
    assert result.outbox_event.command.value == "VERIFY"
    with unit_of_work(uow_factory) as uow:
        attempts = uow.attempts.list_for_operation(OP_ID)
        assert len(attempts) == 1
        assert attempts[0].state is AttemptState.STARTED
        assert attempts[0].outcome is None


def test_replay_execution_applied_is_idempotent(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.EXECUTION_APPLIED)
    command = command_for(scenario, TransitionKind.EXECUTION_APPLIED)
    first = apply_committed(uow_factory, command)
    assert first.outcome is TransitionOutcome.APPLIED
    replay = apply_committed(uow_factory, command)
    assert replay.outcome is TransitionOutcome.ALREADY_APPLIED
    with unit_of_work(uow_factory) as uow:
        attempts = uow.attempts.list_for_operation(OP_ID)
        completed = [item for item in attempts if item.state is AttemptState.COMPLETED]
        assert len(completed) == 1


def test_ready_still_requires_claim_execution(
    uow_factory: sessionmaker[Session],
) -> None:
    from stateback.domain.crash import interpret_execution_crash
    from stateback.domain.enums import CrashInterpretation, EffectOutcome
    from stateback.transitions.commands import ExecutionApplied
    from tests.integration.transitions.conftest import (
        complete_attempt,
        make_started_attempt,
    )
    from tests.unit.domain.fixtures import LATER

    scenario = prefix_ready(uow_factory)
    crash = interpret_execution_crash(
        operation_state=OperationState.READY, attempt_state=None
    )
    assert crash.interpretation is CrashInterpretation.NO_PROVIDER_ATTEMPT
    started = make_started_attempt(
        scenario.operation, attempt_id=scenario.ids.next(), attempt_number=1
    )
    result = apply_committed(
        uow_factory,
        ExecutionApplied(
            kind=TransitionKind.EXECUTION_APPLIED,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=None,
            correlation_id=None,
            reason_code="applied",
            transition_audit_event_id=scenario.ids.next(),
            completed_attempt=complete_attempt(started, outcome=EffectOutcome.APPLIED),
            evidence_audit_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
