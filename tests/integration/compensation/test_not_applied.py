from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

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
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import ReferenceCompensateScript
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    load_compensation_attempts,
    make_execute,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_provider_reject_compensation_goes_compensation_failed(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_FAILED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.FAILED


def test_safe_retry_chains_second_attempt_then_succeeds(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, max_automatic_execution_attempts=2
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

    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.SUCCEEDED


def test_retry_cap_stops_without_third_compensate(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, max_automatic_execution_attempts=2
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

    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATION_FAILED
    assert executed.compensation is not None
    assert executed.compensation.state is CompensationState.FAILED
    assert executed.disposition is CompensationDisposition.ACCEPTED
    assert not adapter._compensate_scripts


def test_safe_retry_uses_unique_ids_beyond_second_attempt(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, max_automatic_execution_attempts=3
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
    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    executed = compensation.execute(
        make_execute(
            seq,
            started.operation.operation_id,
            started.operation.version,
        )
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    attempts = load_compensation_attempts(
        uow_factory, executed.compensation.compensation_id
    )
    assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3]
    assert len({attempt.compensation_attempt_id for attempt in attempts}) == 3
