from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState
from stateback.persistence.uow import unit_of_work
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_operation,
    make_execute,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_original_attempts_remain_after_compensated(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    with unit_of_work(uow_factory) as uow:
        orig_attempts_before = uow.attempts.list_for_operation(op.operation_id)
        assert len(orig_attempts_before) == 1

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    with unit_of_work(uow_factory) as uow:
        orig_attempts_after = uow.attempts.list_for_operation(op.operation_id)
        assert len(orig_attempts_after) == 1
        assert orig_attempts_after[0].attempt_id == orig_attempts_before[0].attempt_id


def test_original_succeeded_audit_remains(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    with unit_of_work(uow_factory) as uow:
        events_before = uow.audit_events.list_for_operation(op.operation_id)
        assert any(
            e.event_type.value == "operation.transitioned.v1" for e in events_before
        )

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    with unit_of_work(uow_factory) as uow:
        events_after = uow.audit_events.list_for_operation(op.operation_id)
        assert len(events_after) > len(events_before)
        # All events_before are still in events_after
        before_ids = {e.audit_event_id for e in events_before}
        after_ids = {e.audit_event_id for e in events_after}
        assert before_ids.issubset(after_ids)


def test_intent_digest_of_operation_unchanged(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation
    original_digest = op.intent.intent_digest

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None

    reloaded = load_operation(uow_factory, op.operation_id)
    assert reloaded.intent.intent_digest == original_digest
