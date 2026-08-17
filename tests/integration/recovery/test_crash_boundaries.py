from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import EffectOutcome, OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.exceptions import SimulatedRecoveryCrash
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import (
    load_verifications,
    make_recovery,
    rebuild_recovery,
)
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import load_operation, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_crash_after_start_commit_leaves_verifying_incomplete_second_recover_verifies(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    crashing = rebuild_recovery(
        uow_factory,
        registry,
        clock,
        crash_after=RecoveryCrashPoint.AFTER_START_COMMIT,
    )
    with pytest.raises(SimulatedRecoveryCrash):
        crashing.recover(
            make_recovery(seq, ids.operation_id, executed.operation.version)
        )
    op = load_operation(uow_factory, ids.operation_id)
    assert op.state is OperationState.VERIFYING
    rows = load_verifications(uow_factory, ids.operation_id)
    assert len(rows) == 1
    _request, result = rows[0]
    assert result is None
    assert adapter._verify_scripts == [ReferenceVerifyScript.UNKNOWN_INCONSISTENT]
    adapter._verify_scripts.clear()
    recovered = rebuild_recovery(uow_factory, registry, clock).recover(
        make_recovery(seq, ids.operation_id, op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED


def test_crash_after_verify_before_result_does_not_persist_observation(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    crashing = rebuild_recovery(
        uow_factory,
        registry,
        clock,
        crash_after=RecoveryCrashPoint.AFTER_VERIFY_BEFORE_RESULT,
    )
    with pytest.raises(SimulatedRecoveryCrash):
        crashing.recover(
            make_recovery(seq, ids.operation_id, executed.operation.version)
        )
    op = load_operation(uow_factory, ids.operation_id)
    assert op.state is not OperationState.SUCCEEDED
    rows = load_verifications(uow_factory, ids.operation_id)
    assert rows[0][1] is None
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    recovered = rebuild_recovery(uow_factory, registry, clock).recover(
        make_recovery(seq, ids.operation_id, op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.FAILED
    assert recovered.verification_evidence is not None
    assert recovered.verification_evidence.outcome is EffectOutcome.NOT_APPLIED


def test_crash_after_result_commit_reuses_durable_result_without_second_verify(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    crashing = rebuild_recovery(
        uow_factory,
        registry,
        clock,
        crash_after=RecoveryCrashPoint.AFTER_RESULT_COMMIT,
    )
    with pytest.raises(SimulatedRecoveryCrash):
        crashing.recover(
            make_recovery(seq, ids.operation_id, executed.operation.version)
        )
    op = load_operation(uow_factory, ids.operation_id)
    rows = load_verifications(uow_factory, ids.operation_id)
    assert rows[0][1] is not None
    assert rows[0][1].outcome is EffectOutcome.APPLIED
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    recovered = rebuild_recovery(uow_factory, registry, clock).recover(
        make_recovery(seq, ids.operation_id, op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED
    assert adapter._verify_scripts == [ReferenceVerifyScript.NOT_APPLIED]


def test_process_restart_uses_postgres_not_recovery_memory(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    from tests.integration.recovery.conftest import run_unknown_timeout

    op = run_unknown_timeout(runtime, seq)
    del recovery
    restarted = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    loaded = load_operation(uow_factory, op.operation_id)
    assert loaded.state is OperationState.UNKNOWN
    assert restarted.recover is not None
