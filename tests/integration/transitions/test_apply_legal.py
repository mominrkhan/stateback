from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AuditEventType
from stateback.persistence.uow import unit_of_work
from stateback.transitions.kinds import KIND_TO_EDGE, TransitionKind
from stateback.transitions.outbox import OUTBOX_COMMAND_FOR_KIND
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import command_for, prepare_source

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize("kind", list(TransitionKind))
def test_every_operation_kind_applies_from_fixture_graph(
    uow_factory: sessionmaker[Session], kind: TransitionKind
) -> None:
    source, target = KIND_TO_EDGE[kind]
    scenario = prepare_source(uow_factory, kind)
    expected_version = (
        1
        if kind is TransitionKind.CREATE_OPERATION
        else (scenario.operation.version + 1)
    )
    command = command_for(scenario, kind)
    result = scenario.apply(command)
    assert result.outcome is TransitionOutcome.APPLIED
    assert result.operation is not None
    assert result.operation.state is target
    assert result.operation.version == expected_version
    with unit_of_work(uow_factory) as uow:
        reloaded = uow.operations.get(result.operation.operation_id)
        assert reloaded is not None
        assert reloaded.state is target
        assert reloaded.version == expected_version
        events = uow.audit_events.list_for_operation(reloaded.operation_id)
        assert events
        last = events[-1]
        if kind is TransitionKind.CREATE_OPERATION:
            assert last.event_type is AuditEventType.OPERATION_CREATED
        else:
            assert last.event_type is AuditEventType.OPERATION_TRANSITIONED
        assert last.from_state is source
        assert last.to_state is target
        pending = [
            item
            for item in uow.outbox_events.list_pending_for_claim(50)
            if item.aggregate_id == reloaded.operation_id
            and item.operation_version == expected_version
        ]
        if kind in OUTBOX_COMMAND_FOR_KIND:
            assert len(pending) == 1
            assert pending[0].state.value == "PENDING"
            assert pending[0].command is OUTBOX_COMMAND_FOR_KIND[kind]
            assert pending[0].operation_version == expected_version
        else:
            assert pending == []
