from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    AuditEventType,
    OperationState,
    OutboxState,
    PolicyVerdict,
    WorkCommand,
)
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.commands import RecoveryCommand
from stateback.recovery.exceptions import SimulatedRecoveryCrash
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import (
    rebuild_recovery,
    run_unknown_timeout,
)
from tests.integration.recovery.idseq import IdSeq, recovery_ids
from tests.integration.runtime.conftest import (
    load_audits,
    load_outbox,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_unknown_start_writes_pending_verify_outbox_not_published(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    adapter: ReferenceAdapter,
    seq: IdSeq,
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    rec_ids = recovery_ids(seq)
    crashing = rebuild_recovery(
        uow_factory,
        registry,
        clock,
        crash_after=RecoveryCrashPoint.AFTER_START_COMMIT,
    )
    with pytest.raises(SimulatedRecoveryCrash):
        crashing.recover(
            RecoveryCommand(
                operation_id=ids.operation_id,
                expected_version=executed.operation.version,
                ids=rec_ids,
                actor=None,
                correlation_id=None,
            )
        )
    matching = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == rec_ids.start_outbox_event_id
    ]
    assert len(matching) == 1
    assert matching[0].command is WorkCommand.VERIFY
    assert matching[0].state is OutboxState.PENDING
    assert matching[0].published_at is None


def test_verification_applied_has_no_new_execute_outbox(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    rec_ids = recovery_ids(seq)
    recovered = recovery.recover(
        RecoveryCommand(
            operation_id=ids.operation_id,
            expected_version=executed.operation.version,
            ids=rec_ids,
            actor=None,
            correlation_id=None,
        )
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED
    retry = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == rec_ids.retry_outbox_event_id
    ]
    assert retry == []


def test_verification_not_applied_retry_writes_pending_execute_outbox(
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
            reason_codes=("allow_two",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    adapter.enqueue_verify(ReferenceVerifyScript.NOT_APPLIED)
    op = run_unknown_timeout(runtime, seq)
    rec_ids = recovery_ids(seq)
    recovered = recovery.recover(
        RecoveryCommand(
            operation_id=op.operation_id,
            expected_version=op.version,
            ids=rec_ids,
            actor=None,
            correlation_id=None,
        )
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.READY
    matching = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == rec_ids.retry_outbox_event_id
    ]
    assert len(matching) == 1
    assert matching[0].command is WorkCommand.EXECUTE
    assert matching[0].state is OutboxState.PENDING
    assert matching[0].published_at is None


def test_verification_inconclusive_has_no_verify_outbox(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONCLUSIVE)
    op = run_unknown_timeout(runtime, seq)
    before = {
        event.event_id
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.VERIFY
    }
    rec_ids = recovery_ids(seq)
    recovered = recovery.recover(
        RecoveryCommand(
            operation_id=op.operation_id,
            expected_version=op.version,
            ids=rec_ids,
            actor=None,
            correlation_id=None,
        )
    )
    assert recovered.operation is not None
    extra = [
        event
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.VERIFY
        and event.event_id not in before
        and event.event_id != rec_ids.start_outbox_event_id
    ]
    assert extra == []


def test_audit_contains_verification_started_and_completed(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    rec_ids = recovery_ids(seq)
    recovered = recovery.recover(
        RecoveryCommand(
            operation_id=ids.operation_id,
            expected_version=executed.operation.version,
            ids=rec_ids,
            actor=None,
            correlation_id=None,
        )
    )
    assert recovered.operation is not None
    types = {event.event_type for event in load_audits(uow_factory, ids.operation_id)}
    assert AuditEventType.VERIFICATION_STARTED in types
    assert AuditEventType.VERIFICATION_COMPLETED in types


def test_unknown_history_remains_after_succeeded(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    rec_ids = recovery_ids(seq)
    recovered = recovery.recover(
        RecoveryCommand(
            operation_id=ids.operation_id,
            expected_version=executed.operation.version,
            ids=rec_ids,
            actor=None,
            correlation_id=None,
        )
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED
    types = {event.event_type for event in load_audits(uow_factory, ids.operation_id)}
    assert AuditEventType.EXECUTION_EVIDENCE_RECORDED in types
