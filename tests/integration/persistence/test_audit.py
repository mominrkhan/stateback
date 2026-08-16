from __future__ import annotations

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError, InternalError
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.audit import AuditEvent
from stateback.domain.enums import CONTRACT_VERSION, AuditEventType
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_from_plain
from stateback.persistence.exceptions import (
    AppendOnlyViolationError,
    DuplicateKeyError,
)
from stateback.persistence.models import AuditEventRow
from stateback.persistence.types import opaque_to_uuid
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.integration.persistence.conftest import (
    AUDIT_ID_2,
    make_audit,
    make_operation,
)
from tests.unit.domain.fixtures import AUDIT_ID, OP_ID, REQUESTER, TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_append_and_order(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit(sequence=1))
        uow.audit_events.append(make_audit(audit_event_id=AUDIT_ID_2, sequence=2))
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(OP_ID)
    assert [event.sequence for event in events] == [1, 2]


def test_duplicate_sequence(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit(sequence=1))
    with pytest.raises(DuplicateKeyError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.audit_events.append(make_audit(audit_event_id=AUDIT_ID_2, sequence=1))
    assert exc.value.reason_code == "duplicate_audit_sequence"


def test_update_blocked_by_trigger(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit())
    uow = UnitOfWork(uow_factory())
    try:
        with pytest.raises(
            (AppendOnlyViolationError, IntegrityError, InternalError, DBAPIError)
        ):
            uow.session.execute(
                update(AuditEventRow)
                .where(AuditEventRow.audit_event_id == opaque_to_uuid(AUDIT_ID))
                .values(reason_code="mutated")
            )
            uow.session.flush()
    finally:
        uow.rollback()
        uow.close()


def test_delete_blocked_by_trigger(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit())
    uow = UnitOfWork(uow_factory())
    try:
        with pytest.raises(
            (AppendOnlyViolationError, IntegrityError, InternalError, DBAPIError)
        ):
            uow.session.execute(
                delete(AuditEventRow).where(
                    AuditEventRow.audit_event_id == opaque_to_uuid(AUDIT_ID)
                )
            )
            uow.session.flush()
    finally:
        uow.rollback()
        uow.close()


def test_transition_event_requires_from_to() -> None:
    with pytest.raises(ContractValidationError) as exc:
        AuditEvent(
            contract_version=CONTRACT_VERSION,
            audit_event_id=AUDIT_ID,
            operation_id=OP_ID,
            sequence=1,
            event_type=AuditEventType.OPERATION_TRANSITIONED,
            from_state=None,
            to_state=None,
            operation_version=1,
            actor=REQUESTER,
            reason_code="transitioned",
            data=json_from_plain({"note": "bad"}),
            correlation_id=None,
            created_at=TS,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_next_sequence_with_lock(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit(sequence=1))
    with unit_of_work(uow_factory) as uow:
        locked = uow.operations.get_for_update(OP_ID)
        assert locked is not None
        assert uow.audit_events.next_sequence(OP_ID) == 2
