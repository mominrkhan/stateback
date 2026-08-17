from __future__ import annotations

import dataclasses
import threading

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    ExecuteCompensationCommand,
    StartCompensationCommand,
)
from stateback.compensation.results import CompensationDisposition, CompensationResult
from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import (
    ReferenceCompensateScript,
    ReferenceVerifyScript,
)
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_compensation_attempts,
    load_operation,
    make_execute,
    make_recover,
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


def test_concurrent_start_one_winner(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    cmd1 = make_start(seq, op.operation_id, op.version)
    cmd2 = make_start(seq, op.operation_id, op.version)

    barrier = threading.Barrier(2)
    lock = threading.Lock()
    results: list[CompensationResult] = []

    def worker(cmd: StartCompensationCommand) -> None:
        barrier.wait()
        res = compensation.start(cmd)
        with lock:
            results.append(res)

    t1 = threading.Thread(target=worker, args=(cmd1,))
    t2 = threading.Thread(target=worker, args=(cmd2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(results) == 2
    accepted = [
        r
        for r in results
        if r.disposition is CompensationDisposition.ACCEPTED
        and r.reason_code == "accepted"
    ]
    assert len(accepted) == 1

    loaded = load_operation(uow_factory, op.operation_id)
    assert loaded.state is OperationState.COMPENSATING
    assert loaded.compensation_id is not None


def test_concurrent_claim_one_winner(
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

    cmd1 = make_execute(seq, started.operation.operation_id, started.operation.version)
    cmd2 = make_execute(seq, started.operation.operation_id, started.operation.version)

    barrier = threading.Barrier(2)
    lock = threading.Lock()
    results: list[CompensationResult] = []

    def worker(cmd: ExecuteCompensationCommand) -> None:
        barrier.wait()
        res = compensation.execute(cmd)
        with lock:
            results.append(res)

    t1 = threading.Thread(target=worker, args=(cmd1,))
    t2 = threading.Thread(target=worker, args=(cmd2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(results) == 2
    # At least one finishes or marks compensated / conflict
    loaded = load_operation(uow_factory, op.operation_id)
    assert loaded.state in {OperationState.COMPENSATING, OperationState.COMPENSATED}


def test_stale_execute_rejects_before_provider_call(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_PROVIDER_KEY), execute_ids(seq)
    )
    assert submitted.operation is not None
    started = compensation.start(
        make_start(
            seq,
            submitted.operation.operation_id,
            submitted.operation.version,
        )
    )
    assert started.operation is not None
    assert started.compensation is not None
    adapter.enqueue_compensate(ReferenceCompensateScript.APPLIED)

    result = compensation.execute(
        make_execute(
            seq,
            started.operation.operation_id,
            started.operation.version - 1,
        )
    )

    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "concurrency_conflict"
    assert adapter._compensate_scripts
    assert not load_compensation_attempts(
        uow_factory, started.compensation.compensation_id
    )


def test_stale_recover_rejects_before_provider_call(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_PROVIDER_KEY), execute_ids(seq)
    )
    assert submitted.operation is not None
    started = compensation.start(
        make_start(
            seq,
            submitted.operation.operation_id,
            submitted.operation.version,
        )
    )
    assert started.operation is not None
    assert started.compensation is not None
    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    unknown = compensation.execute(
        make_execute(
            seq,
            started.operation.operation_id,
            started.operation.version,
        )
    )
    assert unknown.operation is not None
    assert unknown.operation.state is OperationState.COMPENSATION_UNKNOWN
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    stale = dataclasses.replace(
        make_recover(seq, unknown.operation.operation_id, unknown.operation.version),
        expected_version=unknown.operation.version - 1,
    )

    result = compensation.recover(stale)

    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "concurrency_conflict"
    assert adapter._verify_scripts
    loaded = load_operation(uow_factory, unknown.operation.operation_id)
    assert loaded.state is OperationState.COMPENSATION_UNKNOWN
    assert (
        len(
            load_compensation_attempts(
                uow_factory, started.compensation.compensation_id
            )
        )
        == 1
    )
