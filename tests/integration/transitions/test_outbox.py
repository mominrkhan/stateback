from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, OutboxState, WorkCommand
from stateback.persistence.uow import unit_of_work
from stateback.transitions.kinds import TransitionKind
from tests.integration.transitions.conftest import (
    command_for,
    prefix_ready,
    prepare_source,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_policy_allow_inserts_pending_execute_outbox(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.POLICY_ALLOW)
    result = scenario.apply(command_for(scenario, TransitionKind.POLICY_ALLOW))
    assert result.outbox_event is not None
    assert result.outbox_event.command is WorkCommand.EXECUTE
    assert result.outbox_event.state is OutboxState.PENDING
    with unit_of_work(uow_factory) as uow:
        pending = uow.outbox_events.list_pending_for_claim(10)
        assert len(pending) == 1
        assert pending[0].command is WorkCommand.EXECUTE


def test_claim_execution_does_not_insert_outbox(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prefix_ready(uow_factory)
    result = scenario.apply(command_for(scenario, TransitionKind.CLAIM_EXECUTION))
    assert result.outbox_event is None
    with unit_of_work(uow_factory) as uow:
        after_claim = [
            item
            for item in uow.outbox_events.list_pending_for_claim(10)
            if item.operation_version == result.operation_version
        ]
        assert after_claim == []


def test_denied_does_not_insert_outbox(uow_factory: sessionmaker[Session]) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.POLICY_DENY)
    result = scenario.apply(command_for(scenario, TransitionKind.POLICY_DENY))
    assert result.operation is not None
    assert result.operation.state is OperationState.DENIED
    assert result.outbox_event is None


def test_no_mark_published_in_transitions_source() -> None:
    root = Path("src/stateback/transitions")
    for path in root.rglob("*.py"):
        assert "mark_published" not in path.read_text()
