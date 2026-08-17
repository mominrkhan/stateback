from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.service import CompensationService
from stateback.domain.enums import CompensationKind, CompensationState, OperationState
from stateback.providers.reference.store import ReferenceStore
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_compensation,
    make_execute,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_exact_compensation_from_succeeded_marks_compensated(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    store: ReferenceStore,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.operation.state is OperationState.COMPENSATING

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.SUCCEEDED
    assert executed.compensation.kind is CompensationKind.EXACT

    row = store.get_by_resource_id("res-1")
    assert row is not None
    assert row.compensated is True


def test_exact_kind_unchanged_after_success(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.compensation is not None
    assert started.compensation.kind is CompensationKind.EXACT

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.compensation is not None
    assert executed.compensation.kind is CompensationKind.EXACT

    reloaded = load_compensation(uow_factory, executed.compensation.compensation_id)
    assert reloaded is not None
    assert reloaded.kind is CompensationKind.EXACT
