from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import ExecuteCompensationCommand
from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import PolicyVerdict
from stateback.persistence.uow import unit_of_work
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
from stateback.transitions.commands import ClaimCompensationExecution
from stateback.transitions.kinds import CompensationProgressKind
from stateback.transitions.service import TransitionService
from tests.integration.compensation.conftest import (
    load_compensation_attempts,
    make_execute,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq, compensation_ids
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids
from tests.unit.domain.fixtures import TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_second_start_is_already_applied(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started1 = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started1.disposition is CompensationDisposition.ACCEPTED
    assert started1.reason_code == "accepted"
    assert started1.operation is not None

    started2 = compensation.start(
        make_start(seq, op.operation_id, started1.operation.version)
    )
    assert started2.disposition is CompensationDisposition.ACCEPTED
    assert started2.reason_code == "already_applied"


def test_stable_provider_key_across_retry_attempts(
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
    assert executed.compensation is not None

    attempts = load_compensation_attempts(
        uow_factory, executed.compensation.compensation_id
    )
    assert len(attempts) == 2
    assert attempts[0].provider_idempotency_key is not None
    assert attempts[0].provider_idempotency_key == attempts[1].provider_idempotency_key


def test_execute_in_flight_on_started_attempt(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.compensation is not None

    # Manually claim attempt to leave it in STARTED
    c_ids = compensation_ids(seq)
    from stateback.compensation.request import build_started_attempt
    from stateback.providers.reference.effects import REFERENCE_DESCRIPTORS

    descriptor = REFERENCE_DESCRIPTORS[op.intent.effect]
    started_attempt = build_started_attempt(
        compensation_id=started.compensation.compensation_id,
        attempt_id=c_ids.compensation_attempt_id,
        attempt_number=1,
        descriptor=descriptor,
        clock=runtime._clock,
    )
    transitions = TransitionService()
    with unit_of_work(uow_factory) as uow:
        claimed = transitions.apply(
            uow,
            ClaimCompensationExecution(
                kind=CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION,
                operation_id=op.operation_id,
                expected_operation_version=started.operation.version,
                compensation_id=started.compensation.compensation_id,
                expected_compensation_version=started.compensation.version,
                attempt=started_attempt,
                attempt_audit_event_id=c_ids.claim_attempt_audit_event_id,
                occurred_at=TS,
                actor=None,
                correlation_id=None,
                reason_code="claim",
            ),
        )
    assert claimed.compensation is not None

    # Calling execute when attempt is STARTED -> IN_FLIGHT
    res = compensation.execute(
        ExecuteCompensationCommand(
            operation_id=op.operation_id,
            expected_version=claimed.operation.version
            if claimed.operation
            else started.operation.version,
            ids=compensation_ids(seq),
            actor=None,
            correlation_id=None,
        )
    )
    assert res.disposition is CompensationDisposition.IN_FLIGHT
