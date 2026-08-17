from __future__ import annotations

import dataclasses
from typing import cast

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import AuditEventType, OperationState, PrincipalType
from stateback.domain.refs import PrincipalRef
from stateback.persistence.uow import unit_of_work
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import (
    ReferenceCompensateScript,
    ReferenceExecuteScript,
)
from stateback.runtime import SynchronousRuntime
from stateback.transitions.commands import UnknownEscalate
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.service import TransitionService
from tests.integration.compensation.conftest import (
    load_compensation,
    make_execute,
    make_operator,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids
from tests.unit.domain.fixtures import TS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]

OPERATOR_ACTOR = PrincipalRef(
    type=PrincipalType.OPERATOR,
    id="operator-1",
    display_name="TestOperator",
)


def test_operator_start_from_manual_intervention(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    assert submitted.operation.state is OperationState.UNKNOWN

    transitions = TransitionService()
    with unit_of_work(uow_factory) as uow:
        escalated = transitions.apply(
            uow,
            UnknownEscalate(
                kind=TransitionKind.UNKNOWN_ESCALATE,
                operation_id=submitted.operation.operation_id,
                expected_version=submitted.operation.version,
                occurred_at=TS,
                actor=OPERATOR_ACTOR,
                correlation_id=None,
                reason_code="escalate",
                transition_audit_event_id=seq.next(),
                manual_audit_event_id=seq.next(),
            ),
        )
    assert escalated.operation is not None
    assert escalated.operation.state is OperationState.MANUAL_INTERVENTION

    cmd = make_operator(
        seq,
        escalated.operation.operation_id,
        escalated.operation.version,
        actor=OPERATOR_ACTOR,
        reason_code="operator_requested_customer_remediation",
    )
    started = compensation.start_operator_compensation(cmd)
    assert started.disposition is CompensationDisposition.ACCEPTED
    assert started.operation is not None
    assert started.operation.state is OperationState.COMPENSATING
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(started.operation.operation_id)
    operator_event = next(
        event
        for event in events
        if event.audit_event_id == cmd.ids.operator_audit_event_id
        and event.event_type is AuditEventType.OPERATOR_ACTION
    )
    assert operator_event.reason_code == "operator_requested_customer_remediation"


def test_operator_start_does_not_require_automatic_flag(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    # Default obligations have automatic_compensation_allowed = False
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    cmd = make_operator(seq, op.operation_id, op.version, actor=OPERATOR_ACTOR)
    started = compensation.start_operator_compensation(cmd)
    assert started.disposition is CompensationDisposition.ACCEPTED
    assert started.operation is not None
    assert started.operation.state is OperationState.COMPENSATING


def test_operator_retry_failed(
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

    # Operator retries failed compensation:
    adapter.enqueue_compensate(ReferenceCompensateScript.APPLIED)
    retry_cmd = make_operator(
        seq,
        executed.operation.operation_id,
        executed.operation.version,
        actor=OPERATOR_ACTOR,
    )
    retried = compensation.retry_failed_compensation(retry_cmd)
    assert retried.disposition is CompensationDisposition.ACCEPTED
    assert retried.operation is not None
    assert retried.operation.state is OperationState.COMPENSATED


def test_operator_escalate_does_not_rewrite_compensation_row(
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
    comp_id = started.compensation.compensation_id
    comp_ver_before = started.compensation.version
    comp_state_before = started.compensation.state

    cmd = make_operator(
        seq,
        started.operation.operation_id,
        started.operation.version,
        actor=OPERATOR_ACTOR,
    )
    escalated = compensation.escalate(cmd)
    assert escalated.disposition is CompensationDisposition.ACCEPTED
    assert escalated.operation is not None
    assert escalated.operation.state is OperationState.MANUAL_INTERVENTION

    # Compensation row unchanged (E20b)
    loaded_comp = load_compensation(uow_factory, comp_id)
    assert loaded_comp is not None
    assert loaded_comp.state is comp_state_before
    assert loaded_comp.version == comp_ver_before


def test_stale_expected_version_conflicts(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    stale_cmd = make_operator(
        seq,
        op.operation_id,
        op.version - 1,  # stale version
        actor=OPERATOR_ACTOR,
    )
    result = compensation.start_operator_compensation(stale_cmd)
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "concurrency_conflict"


def test_stale_failed_retry_conflicts(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
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
    failed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert failed.operation is not None
    assert failed.operation.state is OperationState.COMPENSATION_FAILED
    stale = make_operator(
        seq,
        failed.operation.operation_id,
        failed.operation.version - 1,
        actor=OPERATOR_ACTOR,
    )
    result = compensation.retry_failed_compensation(stale)
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "concurrency_conflict"


def test_stale_escalation_conflicts(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    started = compensation.start(
        make_start(
            seq,
            submitted.operation.operation_id,
            submitted.operation.version,
        )
    )
    assert started.operation is not None
    stale = make_operator(
        seq,
        started.operation.operation_id,
        started.operation.version - 1,
        actor=OPERATOR_ACTOR,
    )
    result = compensation.escalate(stale)
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "concurrency_conflict"


def test_operator_start_requires_actor(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    command = make_operator(
        seq,
        submitted.operation.operation_id,
        submitted.operation.version,
        actor=OPERATOR_ACTOR,
    )
    missing_actor = dataclasses.replace(command, actor=cast(PrincipalRef, None))
    result = compensation.start_operator_compensation(missing_actor)
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "actor_required"
