from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import EffectOutcome, OperationState
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.exceptions import MalformedRowError
from stateback.persistence.types import opaque_to_uuid
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.integration.persistence.conftest import (
    make_completed_unknown_attempt,
    make_operation,
    make_started_attempt,
)
from tests.unit.domain.fixtures import ATTEMPT_ID, AUDIT_ID, OP_ID, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_reload_after_new_engine(
    uow_factory: sessionmaker[Session], database_url: str
) -> None:
    operation = make_operation()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
    engine = create_engine_from_url(database_url)
    try:
        with unit_of_work(session_factory(engine)) as uow:
            loaded = uow.operations.get(OP_ID)
    finally:
        engine.dispose()
    assert loaded == operation


def test_reload_unknown_outcome_distinct_from_failed(
    uow_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation(state=OperationState.EXECUTING))
        uow.attempts.insert(make_started_attempt())
        uow.attempts.complete(make_completed_unknown_attempt())
    with unit_of_work(uow_factory) as uow:
        attempt = uow.attempts.get(ATTEMPT_ID)
        operation = uow.operations.get(OP_ID)
    assert attempt is not None
    assert attempt.outcome is EffectOutcome.UNKNOWN
    assert operation is not None
    assert operation.state is OperationState.EXECUTING


def test_reload_rejects_unknown_enum(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    uow = UnitOfWork(uow_factory())
    try:
        uow.session.execute(
            text("ALTER TABLE operations DROP CONSTRAINT ck_operations_state")
        )
        uow.session.execute(
            text(
                "UPDATE operations SET state = 'PROBABLY_APPLIED' WHERE operation_id = :id"
            ),
            {"id": opaque_to_uuid(OP_ID)},
        )
        uow.session.expire_all()
        with pytest.raises(MalformedRowError):
            uow.operations.get(OP_ID)
    finally:
        uow.rollback()
        uow.close()


def test_reload_rejects_secret_in_audit(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    uow = UnitOfWork(uow_factory())
    try:
        uow.session.execute(
            text(
                """
                INSERT INTO audit_events (
                  audit_event_id, contract_version, operation_id, sequence,
                  event_type, from_state, to_state, operation_version, actor,
                  reason_code, data, correlation_id, created_at
                ) VALUES (
                  :audit_id, 'v1', :operation_id, 1,
                  'operation.created.v1', NULL, NULL, 1, NULL,
                  'created', '{"token": "abc"}'::jsonb, NULL, :created_at
                )
                """
            ),
            {
                "audit_id": opaque_to_uuid(AUDIT_ID),
                "operation_id": opaque_to_uuid(OP_ID),
                "created_at": TS.value,
            },
        )
        uow.session.flush()
        with pytest.raises(MalformedRowError):
            uow.audit_events.list_for_operation(OP_ID)
    finally:
        uow.rollback()
        uow.close()


def test_intent_immutable_bytes(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    digest = operation.intent.intent_digest
    arguments = operation.intent.to_wire()["arguments"]
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
    assert loaded is not None
    assert loaded.intent.intent_digest == digest
    assert loaded.intent.to_wire()["arguments"] == arguments
