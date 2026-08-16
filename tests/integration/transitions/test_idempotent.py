from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    OperationState,
)
from stateback.domain.intent import IntentEnvelope, operation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.persistence.uow import unit_of_work
from stateback.transitions.commands import CreateOperation
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from tests.integration.transitions.conftest import (
    IdSeq,
    apply_committed,
    command_for,
    make_operation,
    prepare_source,
)
from tests.unit.domain.fixtures import EFFECT, OP_ID, REQUESTER, RISK, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_replay_same_expected_version_after_success_is_already_applied(
    uow_factory: sessionmaker[Session],
) -> None:
    scenario = prepare_source(uow_factory, TransitionKind.POLICY_ALLOW)
    command = command_for(scenario, TransitionKind.POLICY_ALLOW)
    first = apply_committed(uow_factory, command)
    assert first.outcome is TransitionOutcome.APPLIED
    replay = apply_committed(uow_factory, command)
    assert replay.outcome is TransitionOutcome.ALREADY_APPLIED
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(scenario.operation.operation_id)
        transitioned = [
            item
            for item in events
            if item.event_type.value == "operation.transitioned.v1"
        ]
        assert len(transitioned) == 1
        pending = uow.outbox_events.list_pending_for_claim(10)
        assert len(pending) == 1
        loaded = uow.operations.get(scenario.operation.operation_id)
        assert loaded is not None
        assert loaded.version == first.operation_version


def test_create_replay_same_id_and_digest_is_already_applied(
    uow_factory: sessionmaker[Session],
) -> None:
    ids = IdSeq()
    operation = make_operation()
    command = CreateOperation(
        kind=TransitionKind.CREATE_OPERATION,
        operation=operation,
        occurred_at=TS,
        actor=REQUESTER,
        correlation_id=None,
        reason_code="created",
        created_audit_event_id=ids.next(),
    )
    first = apply_committed(uow_factory, command)
    assert first.outcome is TransitionOutcome.APPLIED
    replay = apply_committed(uow_factory, command)
    assert replay.outcome is TransitionOutcome.ALREADY_APPLIED
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(operation.operation_id)
        assert len(events) == 1


def test_create_replay_same_id_different_digest_rejected(
    uow_factory: sessionmaker[Session],
) -> None:
    ids = IdSeq()
    first_op = make_operation()
    apply_committed(
        uow_factory,
        CreateOperation(
            kind=TransitionKind.CREATE_OPERATION,
            operation=first_op,
            occurred_at=TS,
            actor=REQUESTER,
            correlation_id=None,
            reason_code="created",
            created_audit_event_id=ids.next(),
        ),
    )
    other_intent = IntentEnvelope.from_parts(
        effect=EFFECT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"name": "other"}),
        arguments_ref=None,
        requester=REQUESTER,
        requested_at=TS,
        metadata=(),
    )
    other = Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=OperationState.PENDING_POLICY,
        version=1,
        intent=other_intent,
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )
    result = apply_committed(
        uow_factory,
        CreateOperation(
            kind=TransitionKind.CREATE_OPERATION,
            operation=other,
            occurred_at=TS,
            actor=REQUESTER,
            correlation_id=None,
            reason_code="created",
            created_audit_event_id=ids.next(),
        ),
    )
    assert result.outcome is TransitionOutcome.REJECTED
    assert result.reason_code == "intent_conflict"
