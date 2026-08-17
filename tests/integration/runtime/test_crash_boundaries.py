from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AttemptState, EffectOutcome, OperationState
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SimulatedCrash, SynchronousRuntime
from stateback.runtime.faults import RuntimeCrashPoint
from tests.integration.runtime.conftest import (
    load_attempts,
    load_operation,
    make_execute,
    make_recover,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def _crashing(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    point: RuntimeCrashPoint,
) -> SynchronousRuntime:
    return rebuild_runtime(
        uow_factory,
        registry,
        clock,  # type: ignore[arg-type]
        crash_after=point,
    )


def test_crash_after_intent_commit_leaves_pending_policy_and_no_store_row(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = _crashing(
        uow_factory, registry, clock, RuntimeCrashPoint.AFTER_INTENT_COMMIT
    )
    ids = submit_ids(seq)
    command = make_submit(seq, ids=ids)
    with pytest.raises(SimulatedCrash):
        runtime.submit(command)
    op = load_operation(uow_factory, ids.operation_id)
    assert op.state is OperationState.PENDING_POLICY
    assert store.all_resources() == ()
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    second = recovered.submit(command)
    assert second.operation is not None
    assert second.operation.state is OperationState.READY
    assert store.all_resources() == ()


def test_crash_after_policy_commit_leaves_ready_execute_can_proceed(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    seq: IdSeq,
) -> None:
    runtime = _crashing(
        uow_factory, registry, clock, RuntimeCrashPoint.AFTER_POLICY_COMMIT
    )
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash):
        runtime.submit(make_submit(seq, ids=ids))
    op = load_operation(uow_factory, ids.operation_id)
    assert op.state is OperationState.READY
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    executed = recovered.execute(make_execute(seq, ids.operation_id, op.version))
    assert executed.operation is not None
    assert executed.operation.state is OperationState.SUCCEEDED


def test_crash_after_claim_recover_goes_unknown_without_second_execute(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = _crashing(
        uow_factory, registry, clock, RuntimeCrashPoint.AFTER_CLAIM_COMMIT
    )
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash):
        runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert store.all_resources() == ()
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    op = load_operation(uow_factory, ids.operation_id)
    result = recovered.recover(make_recover(seq, ids.operation_id, op.version))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert len(attempts) == 1
    assert attempts[0].state is AttemptState.STARTED
    assert store.all_resources() == ()


def test_crash_after_execute_before_evidence_recover_goes_unknown_store_keeps_row(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = _crashing(
        uow_factory,
        registry,
        clock,
        RuntimeCrashPoint.AFTER_EXECUTE_BEFORE_EVIDENCE,
    )
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash):
        runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert len(store.all_resources()) == 1
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    op = load_operation(uow_factory, ids.operation_id)
    result = recovered.recover(make_recover(seq, ids.operation_id, op.version))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert attempts[0].state is AttemptState.STARTED
    assert len(store.all_resources()) == 1


def test_crash_after_evidence_commit_recover_applies_succeeded_without_second_execute(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = _crashing(
        uow_factory, registry, clock, RuntimeCrashPoint.AFTER_EVIDENCE_COMMIT
    )
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash):
        runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert attempts[0].state is AttemptState.COMPLETED
    assert attempts[0].outcome is EffectOutcome.APPLIED
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    op = load_operation(uow_factory, ids.operation_id)
    result = recovered.recover(make_recover(seq, ids.operation_id, op.version))
    assert result.operation is not None
    assert result.operation.state is OperationState.SUCCEEDED
    assert len(store.all_resources()) == 1


def test_process_restart_uses_postgres_not_runtime_memory(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    del runtime
    restarted = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    del restarted
    loaded = load_operation(uow_factory, ids.operation_id)
    assert loaded.operation_id == ids.operation_id
    assert loaded.state is OperationState.SUCCEEDED
