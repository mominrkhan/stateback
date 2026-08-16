from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.transitions.commands import CancelReady, ClaimExecution
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    OPERATOR,
    _claim,
    _create,
    _execution_unknown,
    apply_committed,
    complete_attempt,
    make_started_attempt,
    prefix_ready,
)
from tests.unit.domain.fixtures import LATER

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_executing_to_cancelled_rejected(uow_factory: sessionmaker[Session]) -> None:
    scenario = _claim(prefix_ready(uow_factory))
    result = apply_committed(
        uow_factory,
        CancelReady(
            kind=TransitionKind.CANCEL_READY,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=OPERATOR,
            correlation_id=None,
            reason_code="cancel",
            transition_audit_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code in {
        "unlisted_operation_transition",
        "source_state_mismatch",
    }


def test_ready_to_succeeded_rejected(uow_factory: sessionmaker[Session]) -> None:
    from stateback.domain.enums import EffectOutcome
    from stateback.transitions.commands import ExecutionApplied

    scenario = prefix_ready(uow_factory)
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
    assert result.reason_code == "source_state_mismatch"


def test_unknown_to_executing_rejected(uow_factory: sessionmaker[Session]) -> None:
    scenario = _execution_unknown(_claim(prefix_ready(uow_factory)))
    attempt = make_started_attempt(
        scenario.operation, attempt_id=scenario.ids.next(), attempt_number=2
    )
    result = apply_committed(
        uow_factory,
        ClaimExecution(
            kind=TransitionKind.CLAIM_EXECUTION,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=None,
            correlation_id=None,
            reason_code="claim",
            transition_audit_event_id=scenario.ids.next(),
            attempt=attempt,
            attempt_audit_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code == "source_state_mismatch"


def test_wrong_source_state_rejected(uow_factory: sessionmaker[Session]) -> None:
    scenario = _create(uow_factory)
    result = apply_committed(
        uow_factory,
        CancelReady(
            kind=TransitionKind.CANCEL_READY,
            operation_id=scenario.operation.operation_id,
            expected_version=scenario.operation.version,
            occurred_at=LATER,
            actor=OPERATOR,
            correlation_id=None,
            reason_code="cancel",
            transition_audit_event_id=scenario.ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code == "source_state_mismatch"


def test_update_cas_only_called_from_service() -> None:
    from pathlib import Path

    root = Path("src/stateback")
    hits: list[str] = []
    for path in root.rglob("*.py"):
        if "persistence" in path.parts:
            continue
        if "update_cas(" in path.read_text():
            hits.append(str(path))
    assert hits == ["src/stateback/transitions/service.py"]
