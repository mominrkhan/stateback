from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import (
    CompensationState,
    OperationState,
    PolicyVerdict,
    VerificationTarget,
)
from stateback.persistence.uow import unit_of_work
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import (
    ReferenceCompensateScript,
    ReferenceVerifyScript,
)
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    make_execute,
    make_recover,
    make_start,
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


def test_require_verification_calls_verify_with_target_compensation(
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
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )

    # First verify for original recovery to reach SUCCEEDED
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.operation.state is OperationState.COMPENSATING

    # Second verify for compensation verification
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    with unit_of_work(uow_factory) as uow:
        verifications = uow.verifications.list_for_operation(op.operation_id)
        comp_verifs = [
            request
            for request, _ in verifications
            if request.target is VerificationTarget.COMPENSATION
        ]
        assert len(comp_verifs) >= 1
        assert comp_verifs[0].target is VerificationTarget.COMPENSATION


def test_verify_applied_compensated(
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
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.SUCCEEDED


def test_verify_not_applied_retries_compensate_when_safe(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS,
        max_automatic_execution_attempts=2,
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
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )

    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_PROVIDER_KEY), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    unknown = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert unknown.operation is not None
    assert unknown.operation.state is OperationState.COMPENSATION_UNKNOWN

    # E42 verification proves the ambiguous attempt did not apply, authorizing
    # one safe retry with the stable provider key.
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    executed = compensation.recover(
        make_recover(seq, unknown.operation.operation_id, unknown.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.SUCCEEDED


def test_verify_inconsistent_escalates(
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
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.MANUAL_INTERVENTION
    assert executed.disposition is CompensationDisposition.ACCEPTED


def test_unknown_parent_e42_starts_compensation_verification_without_second_compensate(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_PROVIDER_KEY), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_UNKNOWN

    # Now recover: E42 should verify without calling compensate again
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    recovered = compensation.recover(
        make_recover(seq, executed.operation.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.COMPENSATED
    assert recovered.compensation is not None
    assert recovered.compensation.state is CompensationState.SUCCEEDED


def test_inconclusive_verification_escalates_at_configured_budget(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS,
        max_automatic_recovery_attempts=3,
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
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
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
    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    current = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert current.operation is not None
    assert current.operation.state is OperationState.COMPENSATION_UNKNOWN

    for expected_state in (
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.MANUAL_INTERVENTION,
    ):
        adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONCLUSIVE)
        current = compensation.recover(
            make_recover(
                seq,
                current.operation.operation_id,
                current.operation.version,
            )
        )
        assert current.operation is not None
        assert current.operation.state is expected_state
    assert not adapter._verify_scripts
