from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, PolicyVerdict, WorkCommand
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import ReferenceVerifyScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery, run_unknown_timeout
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import (
    load_outbox,
    make_execute,
    rebuild_runtime,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_verify_not_applied_with_exec_cap_two_reaches_ready(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, max_automatic_execution_attempts=2
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow_two",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
    )
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.READY
    timeout_rows = store.all_resources()
    assert len(timeout_rows) == 1
    execute_pending = [
        event
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.EXECUTE
        and event.aggregate_id == op.operation_id
    ]
    assert any(event.state.value == "PENDING" for event in execute_pending)
    executed = runtime.execute(
        make_execute(seq, op.operation_id, recovered.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.SUCCEEDED


def test_verify_not_applied_at_exec_cap_one_reaches_failed(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.FAILED
