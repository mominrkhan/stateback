from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.exceptions import SimulatedCompensationCrash
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import CompensationState, OperationState, PolicyVerdict
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
from tests.integration.compensation.conftest import (
    load_compensation,
    load_compensation_attempts,
    load_operation,
    make_execute,
    make_recover,
    make_start,
    rebuild_compensation,
    run_to_succeeded_via_recovery,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_crash_after_start_leaves_pending_no_compensate(
    runtime: SynchronousRuntime,
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_START_COMMIT,
    )
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.start(make_start(seq, op.operation_id, op.version))

    loaded_op = load_operation(uow_factory, op.operation_id)
    assert loaded_op.state is OperationState.COMPENSATING
    assert loaded_op.compensation_id is not None

    loaded_comp = load_compensation(uow_factory, loaded_op.compensation_id)
    assert loaded_comp is not None
    assert loaded_comp.state is CompensationState.PENDING

    row = store.get_by_resource_id("res-1")
    assert row is not None
    assert row.compensated is False


def test_crash_after_claim_before_compensate_recover_unknowns(
    runtime: SynchronousRuntime,
    registry: CapabilityRegistry,
    clock: FixedClock,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    comp = rebuild_compensation(uow_factory, registry, clock)
    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_CLAIM_COMMIT,
    )
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    recovered = comp.recover(
        make_recover(seq, started.operation.operation_id, started.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATION_UNKNOWN
    assert recovered.compensation is not None
    assert recovered.compensation.state is CompensationState.UNKNOWN


def test_crash_after_compensate_applied_before_evidence_recover_unknowns(
    runtime: SynchronousRuntime,
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    comp = rebuild_compensation(uow_factory, registry, clock)
    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_COMPENSATE_BEFORE_EVIDENCE,
    )
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    row = store.get_by_resource_id("res-1")
    assert row is not None
    assert row.compensated is True

    recovered = comp.recover(
        make_recover(seq, started.operation.operation_id, started.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATION_UNKNOWN


def test_crash_after_evidence_before_verify_resumes_verify(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    comp = rebuild_compensation(uow_factory, registry, clock)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)

    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_EVIDENCE_COMMIT,
    )
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    loaded_op = load_operation(uow_factory, op.operation_id)
    assert loaded_op.state is OperationState.COMPENSATING
    assert loaded_op.compensation_id is not None
    loaded_comp = load_compensation(uow_factory, loaded_op.compensation_id)
    assert loaded_comp is not None
    assert loaded_comp.state is CompensationState.VERIFYING

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    recovered = comp.recover(
        make_recover(seq, loaded_op.operation_id, loaded_op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATED


def test_crash_after_verify_start_commit_resumes_without_second_compensate(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    comp = rebuild_compensation(uow_factory, registry, clock)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)
    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_VERIFY_START_COMMIT,
    )
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    loaded_op = load_operation(uow_factory, op.operation_id)
    assert loaded_op.compensation_id is not None
    loaded_comp = load_compensation(uow_factory, loaded_op.compensation_id)
    assert loaded_comp is not None
    assert loaded_comp.state is CompensationState.VERIFYING
    assert (
        len(load_compensation_attempts(uow_factory, loaded_comp.compensation_id)) == 1
    )

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    recovered = comp.recover(
        make_recover(seq, loaded_op.operation_id, loaded_op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATED
    assert (
        len(load_compensation_attempts(uow_factory, loaded_comp.compensation_id)) == 1
    )


def test_crash_after_verify_before_result_does_not_keep_unpersisted_applied(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    comp = rebuild_compensation(uow_factory, registry, clock)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)

    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_VERIFY_BEFORE_RESULT,
    )
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    loaded_op = load_operation(uow_factory, op.operation_id)
    assert loaded_op.state is OperationState.COMPENSATING

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    recovered = comp.recover(
        make_recover(seq, loaded_op.operation_id, loaded_op.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATED


def test_crash_after_verify_result_commit_recovers_as_already_applied(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    comp = rebuild_compensation(uow_factory, registry, clock)
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)
    started = comp.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    crashing_comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_VERIFY_RESULT_COMMIT,
    )
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    with pytest.raises(SimulatedCompensationCrash):
        crashing_comp.execute(
            make_execute(seq, started.operation.operation_id, started.operation.version)
        )

    loaded_op = load_operation(uow_factory, op.operation_id)
    assert loaded_op.state is OperationState.COMPENSATED
    assert loaded_op.compensation_id is not None
    attempts = load_compensation_attempts(uow_factory, loaded_op.compensation_id)
    assert len(attempts) == 1

    recovered = comp.recover(
        make_recover(seq, loaded_op.operation_id, loaded_op.version)
    )
    assert recovered.disposition is CompensationDisposition.ACCEPTED
    assert recovered.reason_code == "already_applied"
    assert len(load_compensation_attempts(uow_factory, loaded_op.compensation_id)) == 1


def test_replay_after_compensated_is_already_applied(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    replay = compensation.execute(
        make_execute(seq, executed.operation.operation_id, executed.operation.version)
    )
    assert replay.disposition is CompensationDisposition.ACCEPTED
    assert replay.reason_code == "already_applied"
