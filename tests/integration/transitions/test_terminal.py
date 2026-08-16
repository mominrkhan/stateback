from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    command_for,
    prepare_source,
)
from tests.unit.domain.fixtures import LATER

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _reject_follow_up(
    uow_factory: sessionmaker[Session], terminal_kind: TransitionKind
) -> None:
    from stateback.transitions.commands import CancelReady
    from tests.integration.transitions.conftest import OPERATOR, apply_committed

    scenario = prepare_source(uow_factory, terminal_kind)
    result = scenario.apply(command_for(scenario, terminal_kind))
    assert result.operation is not None
    follow = apply_committed(
        uow_factory,
        CancelReady(
            kind=TransitionKind.CANCEL_READY,
            operation_id=result.operation.operation_id,
            expected_version=result.operation.version,
            occurred_at=LATER,
            actor=OPERATOR,
            correlation_id=None,
            reason_code="follow",
            transition_audit_event_id=scenario.ids.next(),
        ),
    )
    assert follow.outcome is TransitionOutcome.REJECTED


@pytest.mark.parametrize(
    "kind",
    [
        TransitionKind.POLICY_DENY,
        TransitionKind.APPROVAL_REJECT,
    ],
)
def test_denied_rejects_any_follow_up(
    uow_factory: sessionmaker[Session], kind: TransitionKind
) -> None:
    _reject_follow_up(uow_factory, kind)


@pytest.mark.parametrize(
    "kind",
    [
        TransitionKind.CANCEL_PENDING_POLICY,
        TransitionKind.CANCEL_READY,
    ],
)
def test_cancelled_rejects_any_follow_up(
    uow_factory: sessionmaker[Session], kind: TransitionKind
) -> None:
    _reject_follow_up(uow_factory, kind)


def test_compensated_rejects_any_follow_up(uow_factory: sessionmaker[Session]) -> None:
    _reject_follow_up(uow_factory, TransitionKind.COMPENSATION_APPLIED)


def test_succeeded_allows_start_compensation(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.SUCCEEDED_START_COMPENSATION)
    result = scenario.apply(
        command_for(scenario, TransitionKind.SUCCEEDED_START_COMPENSATION)
    )
    assert result.outcome is TransitionOutcome.APPLIED
    assert result.operation is not None
    assert result.operation.state is OperationState.COMPENSATING
