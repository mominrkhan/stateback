from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.approval import (
    ApprovalDecisionCommand,
    ApprovalDecisionIds,
    ApprovalDisposition,
    ApprovalExpiryCommand,
    ApprovalService,
    ConfiguredApproverAuthorizer,
)
from stateback.compensation.service import CompensationService
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    OperationState,
    PolicyVerdict,
    PrincipalType,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import WorkMessageV1
from stateback.domain.policy import PolicyObligations
from stateback.domain.refs import PrincipalRef
from stateback.messaging.codec import encode_work_message
from stateback.messaging.worker import AckDecision, WorkHandler
from stateback.persistence.uow import unit_of_work
from stateback.policy import PHASE5_DEFAULT_OBLIGATIONS, PolicyRule, RulePolicyEngine
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from tests.integration.runtime.conftest import (
    load_audits,
    load_operation,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

APPROVER = PrincipalRef(
    type=PrincipalType.HUMAN,
    id="approver-1",
    display_name="Primary Approver",
)
OTHER_APPROVER = PrincipalRef(
    type=PrincipalType.HUMAN,
    id="approver-2",
    display_name="Other Approver",
)


def approval_engine(obligations: PolicyObligations) -> RulePolicyEngine:
    return RulePolicyEngine(
        policy_revision="org-policy-approval-v1",
        rules=(
            PolicyRule(
                rule_id="reference-needs-approval",
                verdict=PolicyVerdict.REQUIRE_APPROVAL,
                obligations=obligations,
                providers=frozenset({"stateback.reference"}),
            ),
        ),
        default_obligations=obligations,
    )


def approval_service(
    uow_factory: sessionmaker[Session], clock: FixedClock
) -> ApprovalService:
    return ApprovalService(
        session_factory=uow_factory,
        authorizer=ConfiguredApproverAuthorizer(
            allowed_principals=frozenset({(APPROVER.type, APPROVER.id)})
        ),
        clock=clock,
    )


def decision_ids(seq: IdSeq) -> ApprovalDecisionIds:
    return ApprovalDecisionIds(
        transition_audit_event_id=seq.next(),
        approval_audit_event_id=seq.next(),
        outbox_event_id=seq.next(),
    )


def decision(
    *,
    seq: IdSeq,
    operation_id: OpaqueId,
    approval_id: OpaqueId,
    expected_version: int,
    actor: PrincipalRef,
    state: ApprovalState,
) -> ApprovalDecisionCommand:
    return ApprovalDecisionCommand(
        operation_id=operation_id,
        approval_id=approval_id,
        expected_version=expected_version,
        decision=state,
        actor=actor,
        reason="reviewed",
        correlation_id="approval-correlation",
        ids=decision_ids(seq),
    )


def test_unauthorized_approver_and_stale_work_cannot_execute(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(PHASE5_DEFAULT_OBLIGATIONS),
    )
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    assert submitted.operation.state is OperationState.AWAITING_APPROVAL
    service = approval_service(uow_factory, clock)
    unauthorized = service.decide(
        decision(
            seq=seq,
            operation_id=ids.operation_id,
            approval_id=ids.approval_id,
            expected_version=submitted.operation.version,
            actor=OTHER_APPROVER,
            state=ApprovalState.APPROVED,
        )
    )
    assert unauthorized.disposition is ApprovalDisposition.UNAUTHORIZED

    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    stale = WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=seq.next(),
        outbox_event_id=seq.next(),
        operation_id=ids.operation_id,
        expected_operation_version=submitted.operation.version,
        command=WorkCommand.EXECUTE,
        correlation_id=None,
        created_at=clock.now(),
    )
    assert (
        handler.handle(encode_work_message(stale), delivery_count=1) is AckDecision.ACK
    )
    assert (
        load_operation(uow_factory, ids.operation_id).state
        is OperationState.AWAITING_APPROVAL
    )
    assert store.all_resources() == ()


def test_authorized_approval_enqueues_then_worker_executes_once(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(PHASE5_DEFAULT_OBLIGATIONS),
    )
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    command = decision(
        seq=seq,
        operation_id=ids.operation_id,
        approval_id=ids.approval_id,
        expected_version=submitted.operation.version,
        actor=APPROVER,
        state=ApprovalState.APPROVED,
    )
    service = approval_service(uow_factory, clock)
    granted = service.decide(command)
    assert granted.disposition is ApprovalDisposition.ACCEPTED
    assert granted.operation is not None
    assert granted.operation.state is OperationState.READY
    duplicate = service.decide(command)
    assert duplicate.disposition is ApprovalDisposition.ACCEPTED
    assert duplicate.reason_code == "already_applied"
    assert store.all_resources() == ()

    with unit_of_work(uow_factory) as uow:
        outbox = uow.outbox_events.list_pending_for_claim(1)[0]
    message = WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=seq.next(),
        outbox_event_id=outbox.event_id,
        operation_id=outbox.aggregate_id,
        expected_operation_version=outbox.operation_version,
        command=outbox.command,
        correlation_id=outbox.correlation_id,
        created_at=outbox.created_at,
    )
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=RecoveryService(
            session_factory=uow_factory, registry=registry, clock=clock
        ),
        compensation=CompensationService(
            session_factory=uow_factory, registry=registry, clock=clock
        ),
        max_deliveries=3,
    )
    payload = encode_work_message(message)
    assert handler.handle(payload, delivery_count=1) is AckDecision.ACK
    assert handler.handle(payload, delivery_count=2) is AckDecision.ACK
    assert len(store.all_resources()) == 1
    audits = load_audits(uow_factory, ids.operation_id)
    assert any(
        event.event_type.value == "approval.decided.v1" and event.actor == APPROVER
        for event in audits
    )


def test_terminal_approval_cannot_be_acknowledged_for_another_operation(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(PHASE5_DEFAULT_OBLIGATIONS),
    )
    first_ids = submit_ids(seq)
    second_ids = submit_ids(seq)
    first = runtime.submit(make_submit(seq, ids=first_ids))
    second = runtime.submit(make_submit(seq, ids=second_ids))
    assert first.operation is not None
    assert second.operation is not None
    service = approval_service(uow_factory, clock)
    approved = service.decide(
        decision(
            seq=seq,
            operation_id=first_ids.operation_id,
            approval_id=first_ids.approval_id,
            expected_version=first.operation.version,
            actor=APPROVER,
            state=ApprovalState.APPROVED,
        )
    )
    assert approved.disposition is ApprovalDisposition.ACCEPTED

    mismatched = service.decide(
        decision(
            seq=seq,
            operation_id=second_ids.operation_id,
            approval_id=first_ids.approval_id,
            expected_version=second.operation.version,
            actor=APPROVER,
            state=ApprovalState.APPROVED,
        )
    )
    assert mismatched.disposition is ApprovalDisposition.REJECTED
    assert mismatched.reason_code == "approval_operation_mismatch"
    assert (
        load_operation(uow_factory, second_ids.operation_id).state
        is OperationState.AWAITING_APPROVAL
    )


def test_terminal_approval_rechecks_current_policy_binding(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(PHASE5_DEFAULT_OBLIGATIONS),
    )
    first_ids = submit_ids(seq)
    second_ids = submit_ids(seq)
    first = runtime.submit(make_submit(seq, ids=first_ids))
    second = runtime.submit(make_submit(seq, ids=second_ids))
    assert first.operation is not None
    assert second.operation is not None
    assert second.operation.current_policy_decision_id is not None
    service = approval_service(uow_factory, clock)
    command = decision(
        seq=seq,
        operation_id=first_ids.operation_id,
        approval_id=first_ids.approval_id,
        expected_version=first.operation.version,
        actor=APPROVER,
        state=ApprovalState.APPROVED,
    )
    approved = service.decide(command)
    assert approved.operation is not None
    with unit_of_work(uow_factory) as uow:
        stale = replace(
            approved.operation,
            version=approved.operation.version + 1,
            current_policy_decision_id=second.operation.current_policy_decision_id,
        )
        uow.operations.update_cas(approved.operation.version, stale)

    duplicate = service.decide(command)
    assert duplicate.disposition is ApprovalDisposition.REJECTED
    assert duplicate.reason_code == "approval_policy_mismatch"


def test_concurrent_approve_reject_has_one_terminal_decision(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(PHASE5_DEFAULT_OBLIGATIONS),
    )
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    approve = decision(
        seq=seq,
        operation_id=ids.operation_id,
        approval_id=ids.approval_id,
        expected_version=submitted.operation.version,
        actor=APPROVER,
        state=ApprovalState.APPROVED,
    )
    reject = decision(
        seq=seq,
        operation_id=ids.operation_id,
        approval_id=ids.approval_id,
        expected_version=submitted.operation.version,
        actor=APPROVER,
        state=ApprovalState.REJECTED,
    )
    service = approval_service(uow_factory, clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(service.decide, (approve, reject)))
    assert (
        sum(result.disposition is ApprovalDisposition.ACCEPTED for result in results)
        == 1
    )
    operation = load_operation(uow_factory, ids.operation_id)
    assert operation.state in {OperationState.READY, OperationState.DENIED}
    with unit_of_work(uow_factory) as uow:
        stored = uow.approvals.get(ids.approval_id)
    assert stored is not None
    assert stored.state in {ApprovalState.APPROVED, ApprovalState.REJECTED}


def test_expired_approval_cancels_operation_and_cannot_be_granted(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = replace(PHASE5_DEFAULT_OBLIGATIONS, approval_expires_at=clock.now())
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=approval_engine(obligations),
    )
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    clock.advance(1)
    service = approval_service(uow_factory, clock)
    expired = service.expire(
        ApprovalExpiryCommand(
            operation_id=ids.operation_id,
            approval_id=ids.approval_id,
            expected_version=submitted.operation.version,
            transition_audit_event_id=seq.next(),
            correlation_id=None,
        )
    )
    assert expired.disposition is ApprovalDisposition.ACCEPTED
    assert expired.operation is not None
    assert expired.operation.state is OperationState.CANCELLED
    grant = service.decide(
        decision(
            seq=seq,
            operation_id=ids.operation_id,
            approval_id=ids.approval_id,
            expected_version=expired.operation.version,
            actor=APPROVER,
            state=ApprovalState.APPROVED,
        )
    )
    assert grant.disposition is ApprovalDisposition.REJECTED
    assert grant.reason_code == "approval_state_conflict"
