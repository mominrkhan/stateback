from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.commands import ScanCommand
from stateback.recovery.service import RecoveryService
from stateback.runtime import SimulatedCrash, SynchronousRuntime
from stateback.runtime.faults import RuntimeCrashPoint
from tests.integration.recovery.idseq import IdSeq, SeqRecoveryIds
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_scan_executing_started_recovers_to_unknown_then_verifies_in_same_scan(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
    recovery: RecoveryService,
) -> None:
    crashing = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        crash_after=RuntimeCrashPoint.AFTER_CLAIM_COMMIT,
    )
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash):
        crashing.run(make_submit(seq, ids=ids), execute_ids(seq))
    results = recovery.scan(
        ScanCommand(ids_for=SeqRecoveryIds(seq), actor=None, correlation_id=None)
    )
    assert results
    loaded_states = [item.operation.state for item in results if item.operation]
    assert OperationState.FAILED in loaded_states
    assert store.all_resources() == ()
    assert adapter._execute_scripts == [ReferenceExecuteScript.NOT_APPLIED_REJECTED]


def test_scan_skips_succeeded(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    assert executed.operation.state is OperationState.SUCCEEDED
    results = recovery.scan(
        ScanCommand(ids_for=SeqRecoveryIds(seq), actor=None, correlation_id=None)
    )
    assert results == ()


def test_scan_empty_returns_empty_tuple(recovery: RecoveryService, seq: IdSeq) -> None:
    results = recovery.scan(
        ScanCommand(ids_for=SeqRecoveryIds(seq), actor=None, correlation_id=None)
    )
    assert results == ()
