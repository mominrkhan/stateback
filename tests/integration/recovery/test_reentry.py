from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.exceptions import SimulatedRecoveryCrash
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.results import RecoveryDisposition
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import (
    make_recovery,
    rebuild_recovery,
)
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import load_operation, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_recover_on_succeeded_does_not_verify(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    assert executed.operation.state is OperationState.SUCCEEDED
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.reason_code == "already_applied"
    assert adapter._verify_scripts == [ReferenceVerifyScript.UNKNOWN_INCONSISTENT]


def test_recover_on_unknown_twice_second_is_already_applied_or_advances_once(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    first = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert first.operation is not None
    assert first.operation.state is OperationState.SUCCEEDED
    second = recovery.recover(
        make_recovery(seq, ids.operation_id, first.operation.version)
    )
    assert second.reason_code == "already_applied"


def test_recover_on_ready_is_already_applied(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    assert submitted.operation.state is OperationState.READY
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, submitted.operation.version)
    )
    assert recovered.disposition is RecoveryDisposition.ACCEPTED
    assert recovered.reason_code == "already_applied"


def test_duplicate_recover_while_verifying_incomplete_is_cas_safe(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
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
    service = rebuild_recovery(uow_factory, registry, clock)
    first = service.recover(make_recovery(seq, ids.operation_id, op.version))
    second = service.recover(
        make_recovery(
            seq,
            ids.operation_id,
            first.operation.version if first.operation is not None else op.version,
        )
    )
    accepted_success = [
        item
        for item in (first, second)
        if item.reason_code == "accepted"
        and item.operation is not None
        and item.operation.state is OperationState.SUCCEEDED
    ]
    assert len(accepted_success) <= 1
    assert first.disposition is RecoveryDisposition.ACCEPTED
    assert second.disposition in {
        RecoveryDisposition.ACCEPTED,
        RecoveryDisposition.REJECTED,
        RecoveryDisposition.INFRASTRUCTURE_FAILURE,
    }
    if second.disposition is RecoveryDisposition.ACCEPTED:
        assert second.reason_code in {"accepted", "already_applied"}
    assert len(store.all_resources()) == 1
