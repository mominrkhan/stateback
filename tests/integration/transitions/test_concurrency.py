from __future__ import annotations

from threading import Barrier, Thread

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AttemptState
from stateback.domain.ids import OpaqueId
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.exceptions import ConcurrencyConflictError
from stateback.persistence.uow import UnitOfWork, unit_of_work
from stateback.transitions.commands import ClaimExecution
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService
from tests.integration.transitions.conftest import make_started_attempt, prefix_ready
from tests.unit.domain.fixtures import LATER, OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_two_claim_execution_one_winner(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    scenario = prefix_ready(uow_factory)
    version = scenario.operation.version
    barrier = Barrier(2)
    outcomes: list[str] = []
    attempt_ids = [
        OpaqueId(value="00000000-0000-4000-8000-0000000000a1"),
        OpaqueId(value="00000000-0000-4000-8000-0000000000a2"),
    ]
    audit_ids = [
        OpaqueId(value="00000000-0000-4000-8000-0000000000b1"),
        OpaqueId(value="00000000-0000-4000-8000-0000000000b2"),
    ]
    attempt_audit_ids = [
        OpaqueId(value="00000000-0000-4000-8000-0000000000c1"),
        OpaqueId(value="00000000-0000-4000-8000-0000000000c2"),
    ]

    def worker(index: int) -> None:
        engine = create_engine_from_url(database_url)
        factory = session_factory(engine)
        uow = UnitOfWork(factory())
        attempt = make_started_attempt(
            scenario.operation,
            attempt_id=attempt_ids[index],
            attempt_number=1,
        )
        try:
            barrier.wait()
            result = TransitionService().apply(
                uow,
                ClaimExecution(
                    kind=TransitionKind.CLAIM_EXECUTION,
                    operation_id=OP_ID,
                    expected_version=version,
                    occurred_at=LATER,
                    actor=None,
                    correlation_id=None,
                    reason_code="claim",
                    transition_audit_event_id=audit_ids[index],
                    attempt=attempt,
                    attempt_audit_event_id=attempt_audit_ids[index],
                ),
            )
            if result.outcome is TransitionOutcome.APPLIED:
                uow.commit()
                outcomes.append("APPLIED")
            else:
                uow.rollback()
                outcomes.append(result.outcome.value)
        except ConcurrencyConflictError:
            uow.rollback()
            outcomes.append("conflict")
        finally:
            uow.close()
            engine.dispose()

    threads = [Thread(target=worker, args=(0,)), Thread(target=worker, args=(1,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("APPLIED") == 1
    assert "conflict" in outcomes or "ALREADY_APPLIED" in outcomes
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
        assert loaded is not None
        assert loaded.version == version + 1
        attempts = uow.attempts.list_for_operation(OP_ID)
        started = [item for item in attempts if item.state is AttemptState.STARTED]
        assert len(started) == 1
