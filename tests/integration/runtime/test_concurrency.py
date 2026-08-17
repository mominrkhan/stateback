from __future__ import annotations

import threading

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.policy import AllowAllPolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SynchronousRuntime
from stateback.runtime.ids import ExecuteIds
from stateback.runtime.results import RuntimeDisposition, RuntimeResult
from tests.integration.runtime.blocking_adapter import BlockingAdapter
from tests.integration.runtime.conftest import (
    load_attempts,
    make_execute,
    make_submit,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_two_threads_claim_one_winner_one_in_flight_or_already_applied(
    uow_factory: sessionmaker[Session],
    store: ReferenceStore,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    inner = ReferenceAdapter(store=store, clock=clock)
    gate = threading.Event()
    adapter = BlockingAdapter(inner, gate)
    registry = CapabilityRegistry()
    registry.register(adapter)
    runtime = SynchronousRuntime(
        session_factory=uow_factory,
        registry=registry,
        policy_engine=AllowAllPolicyEngine(),
        clock=clock,
    )
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    version = submitted.operation.version
    first_ids = execute_ids(seq)
    second_ids = execute_ids(seq)
    results: list[RuntimeResult] = []
    returned = threading.Event()
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def worker(execute_command_ids: ExecuteIds) -> None:
        barrier.wait()
        result = runtime.execute(
            make_execute(
                seq,
                ids.operation_id,
                version,
                ids=execute_command_ids,
            )
        )
        with lock:
            results.append(result)
        returned.set()

    t1 = threading.Thread(target=worker, args=(first_ids,))
    t2 = threading.Thread(target=worker, args=(second_ids,))
    t1.start()
    t2.start()
    assert returned.wait(timeout=10)
    first_result = results[0]
    assert first_result.disposition in {
        RuntimeDisposition.IN_FLIGHT,
        RuntimeDisposition.ACCEPTED,
    }
    if first_result.disposition is RuntimeDisposition.ACCEPTED:
        assert first_result.reason_code == "already_applied"
    gate.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert len(results) == 2
    dispositions = {item.disposition for item in results}
    assert RuntimeDisposition.ACCEPTED in dispositions
    assert len(store.all_resources()) == 1
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert len(attempts) == 1
