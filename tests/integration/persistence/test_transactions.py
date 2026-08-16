from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.persistence.exceptions import ConcurrencyConflictError
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import (
    make_audit,
    make_operation,
    make_outbox,
)
from tests.unit.domain.fixtures import AUDIT_ID, LATER, OP_ID, OUTBOX_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


class Boom(Exception):
    pass


def test_operation_and_audit_commit_together(
    uow_factory: sessionmaker[Session],
) -> None:
    operation = make_operation()
    event = make_audit()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
        uow.audit_events.append(event)
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) == operation
        assert uow.audit_events.list_for_operation(OP_ID) == [event]


def test_operation_and_audit_rollback_together(
    uow_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(Boom):
        with unit_of_work(uow_factory) as uow:
            uow.operations.insert(make_operation())
            uow.audit_events.append(make_audit())
            raise Boom()
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) is None
        assert uow.audit_events.list_for_operation(OP_ID) == []


def test_operation_audit_outbox_atomic_commit(
    uow_factory: sessionmaker[Session],
) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit())
        uow.outbox_events.insert(make_outbox())
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) is not None
        events = uow.audit_events.list_for_operation(OP_ID)
        assert [item.audit_event_id for item in events] == [AUDIT_ID]
        assert uow.outbox_events.get(OUTBOX_ID) is not None


def test_operation_audit_outbox_atomic_rollback(
    uow_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(Boom):
        with unit_of_work(uow_factory) as uow:
            uow.operations.insert(make_operation())
            uow.audit_events.append(make_audit())
            uow.outbox_events.insert(make_outbox())
            raise Boom()
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) is None
        assert uow.audit_events.list_for_operation(OP_ID) == []
        assert uow.outbox_events.get(OUTBOX_ID) is None


def test_failed_cas_does_not_append_audit(uow_factory: sessionmaker[Session]) -> None:
    from tests.integration.persistence.conftest import AUDIT_ID_2

    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.audit_events.append(make_audit(sequence=1))
    with unit_of_work(uow_factory) as uow:
        locked = uow.operations.get_for_update(OP_ID)
        assert locked is not None
        uow.operations.update_cas(
            1,
            replace(locked, version=2, state=OperationState.READY, updated_at=LATER),
        )
    with pytest.raises(ConcurrencyConflictError):
        with unit_of_work(uow_factory) as uow:
            uow.audit_events.append(make_audit(audit_event_id=AUDIT_ID_2, sequence=2))
            uow.operations.update_cas(
                1,
                replace(
                    make_operation(),
                    version=2,
                    state=OperationState.EXECUTING,
                    updated_at=LATER,
                ),
            )
    with unit_of_work(uow_factory) as uow:
        events = uow.audit_events.list_for_operation(OP_ID)
    assert [event.sequence for event in events] == [1]
