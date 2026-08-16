from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AttemptState, EffectOutcome, OperationState
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SimulatedCrash, SynchronousRuntime
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import (
    load_attempts,
    load_audits,
    load_operation,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids
from tests.unit.domain.fixtures import REQUESTER

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_run_mutate_provider_key_reaches_succeeded(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.disposition is RuntimeDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.SUCCEEDED
    resource = store.get_by_resource_id("res-1")
    assert resource is not None
    assert resource.applied is True
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert len(attempts) == 1
    assert attempts[0].state is AttemptState.COMPLETED
    assert attempts[0].outcome is EffectOutcome.APPLIED
    types = {
        event.event_type.value for event in load_audits(uow_factory, ids.operation_id)
    }
    assert "execution.attempt_started.v1" in types
    assert "execution.evidence_recorded.v1" in types
    assert "operation.transitioned.v1" in types


def test_execute_does_not_hold_transaction_across_provider(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    test_claim_commits_before_execute(uow_factory, registry, clock, store, seq)


def test_claim_commits_before_execute(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,  # type: ignore[arg-type]
        crash_after=RuntimeCrashPoint.AFTER_CLAIM_COMMIT,
    )
    ids = submit_ids(seq)
    with pytest.raises(SimulatedCrash) as raised:
        runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert raised.value.point is RuntimeCrashPoint.AFTER_CLAIM_COMMIT
    recovered = rebuild_runtime(uow_factory, registry, clock)  # type: ignore[arg-type]
    del recovered
    op = load_operation(uow_factory, ids.operation_id)
    assert op.state is OperationState.EXECUTING
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert len(attempts) == 1
    assert attempts[0].state is AttemptState.STARTED
    assert store.all_resources() == ()
    assert REQUESTER.id == "agent-1"
