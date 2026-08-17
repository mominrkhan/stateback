from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState
from stateback.domain.jsonutil import json_from_plain
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import (
    ReferenceCompensateScript,
    ReferenceExecuteScript,
)
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_operation,
    make_execute,
    make_scan,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_scan_order_compensating_then_compensation_unknown(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    # Op 1: started compensation (COMPENSATING + PENDING) -> scan will execute to COMPENSATED
    sub1 = runtime.run(
        make_submit(seq, arguments=json_from_plain({"resource_id": "res-scan-1"})),
        execute_ids(seq),
    )
    assert sub1.operation is not None
    start1 = compensation.start(
        make_start(seq, sub1.operation.operation_id, sub1.operation.version)
    )
    assert start1.operation is not None

    # Op 2: unknown compensation (COMPENSATION_UNKNOWN) -> scan will recover
    sub2 = runtime.run(
        make_submit(seq, arguments=json_from_plain({"resource_id": "res-scan-2"})),
        execute_ids(seq),
    )
    assert sub2.operation is not None
    start2 = compensation.start(
        make_start(seq, sub2.operation.operation_id, sub2.operation.version)
    )
    assert start2.operation is not None
    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    exec2 = compensation.execute(
        make_execute(seq, start2.operation.operation_id, start2.operation.version)
    )
    assert exec2.operation is not None
    assert exec2.operation.state is OperationState.COMPENSATION_UNKNOWN

    results = compensation.scan(make_scan(seq))
    assert len(results) >= 1


def test_scan_does_not_retry_compensation_failed(
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

    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_FAILED

    results = compensation.scan(make_scan(seq))
    assert not any(
        r.operation is not None and r.operation.operation_id == op.operation_id
        for r in results
    )
    loaded = load_operation(uow_factory, op.operation_id)
    assert loaded.state is OperationState.COMPENSATION_FAILED


def test_scan_does_not_start_when_automatic_false(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    # SUCCEEDED operation sitting there
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    results = compensation.scan(make_scan(seq))
    assert not any(
        r.operation is not None and r.operation.operation_id == op.operation_id
        for r in results
    )
    loaded = load_operation(uow_factory, op.operation_id)
    assert loaded.state is OperationState.SUCCEEDED
    assert loaded.compensation_id is None


def test_scan_does_not_list_original_unknown(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    # Create an operation in original UNKNOWN
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    assert submitted.operation.state is OperationState.UNKNOWN

    results = compensation.scan(make_scan(seq))
    assert not any(
        r.operation is not None
        and r.operation.operation_id == submitted.operation.operation_id
        for r in results
    )
