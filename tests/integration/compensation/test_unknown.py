from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import CompensationState, OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import ReferenceCompensateScript
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_compensation_attempts,
    make_execute,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_timeout_after_send_is_compensation_unknown(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_UNKNOWN
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.UNKNOWN
    assert executed.disposition is CompensationDisposition.ACCEPTED


def test_malformed_is_compensation_unknown(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_MALFORMED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_UNKNOWN
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.UNKNOWN
    assert executed.disposition is CompensationDisposition.ACCEPTED


def test_unknown_does_not_retry_compensate_immediately(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_UNKNOWN
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.UNKNOWN

    attempts = load_compensation_attempts(
        uow_factory, executed.compensation.compensation_id
    )
    assert len(attempts) == 1
