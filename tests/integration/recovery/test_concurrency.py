from __future__ import annotations

import threading

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.recovery.commands import RecoveryCommand
from stateback.recovery.results import RecoveryDisposition, RecoveryResult
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import load_verifications, make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import load_operation, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_two_threads_one_winner_one_conflict_or_already_applied(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    store: ReferenceStore,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    version = executed.operation.version
    first_command = make_recovery(seq, ids.operation_id, version)
    second_command = make_recovery(seq, ids.operation_id, version)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    results: list[RecoveryResult] = []

    def worker(command: RecoveryCommand) -> None:
        barrier.wait()
        result = recovery.recover(command)
        with lock:
            results.append(result)

    t1 = threading.Thread(target=worker, args=(first_command,))
    t2 = threading.Thread(target=worker, args=(second_command,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert len(results) == 2
    succeeded = [
        item
        for item in results
        if item.operation is not None
        and item.operation.state is OperationState.SUCCEEDED
        and item.reason_code == "accepted"
    ]
    assert len(succeeded) <= 1
    loaded = load_operation(uow_factory, ids.operation_id)
    assert loaded.state is OperationState.SUCCEEDED
    assert len(store.all_resources()) == 1
    rows = load_verifications(uow_factory, ids.operation_id)
    assert 1 <= len(rows) <= 2
    dispositions = {item.disposition for item in results}
    assert RecoveryDisposition.ACCEPTED in dispositions
