from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.service import CompensationService
from stateback.domain.enums import OutboxState, PolicyVerdict, WorkCommand
from stateback.persistence.uow import unit_of_work
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.clock import FixedClock
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    make_execute,
    make_start,
    rebuild_compensation,
    run_to_succeeded_via_recovery,
)
from tests.integration.compensation.idseq import IdSeq, compensation_ids
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_start_inserts_compensate_pending_outbox(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    c_ids = compensation_ids(seq)
    from stateback.compensation.commands import StartCompensationCommand

    cmd = StartCompensationCommand(
        operation_id=op.operation_id,
        expected_version=op.version,
        ids=c_ids,
        actor=None,
        correlation_id=None,
        automatic=False,
    )
    started = compensation.start(cmd)
    assert started.operation is not None

    with unit_of_work(uow_factory) as uow:
        events = [
            event
            for event in uow.outbox_events.list_pending_for_claim(100)
            if event.aggregate_id == op.operation_id
        ]
        matching = [e for e in events if e.event_id == c_ids.start_outbox_event_id]
        assert len(matching) == 1
        assert matching[0].command is WorkCommand.COMPENSATE
        assert matching[0].state is OutboxState.PENDING
        assert matching[0].published_at is None


def test_start_verification_inserts_verify_pending_outbox(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
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
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)

    c_ids = compensation_ids(seq)
    from stateback.compensation.commands import (
        ExecuteCompensationCommand,
        StartCompensationCommand,
    )

    comp = rebuild_compensation(
        uow_factory,
        registry,
        clock,
        crash_after=CompensationCrashPoint.AFTER_EVIDENCE_COMMIT,
    )
    started = comp.start(
        StartCompensationCommand(
            operation_id=op.operation_id,
            expected_version=op.version,
            ids=c_ids,
            actor=None,
            correlation_id=None,
            automatic=False,
        )
    )
    assert started.operation is not None

    from stateback.compensation.exceptions import SimulatedCompensationCrash

    with pytest.raises(SimulatedCompensationCrash):
        comp.execute(
            ExecuteCompensationCommand(
                operation_id=started.operation.operation_id,
                expected_version=started.operation.version,
                ids=c_ids,
                actor=None,
                correlation_id=None,
            )
        )

    with unit_of_work(uow_factory) as uow:
        events = [
            event
            for event in uow.outbox_events.list_pending_for_claim(100)
            if event.aggregate_id == op.operation_id
        ]
        matching = [
            e for e in events if e.event_id == c_ids.verification_outbox_event_id
        ]
        assert len(matching) == 1
        assert matching[0].command is WorkCommand.VERIFY
        assert matching[0].state is OutboxState.PENDING
        assert matching[0].published_at is None


def test_no_mark_published(
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

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None

    with unit_of_work(uow_factory) as uow:
        events = [
            event
            for event in uow.outbox_events.list_pending_for_claim(100)
            if event.aggregate_id == op.operation_id
        ]
        for e in events:
            assert e.published_at is None
            assert e.state is OutboxState.PENDING
