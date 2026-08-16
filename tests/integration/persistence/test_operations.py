from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.persistence.exceptions import (
    ConcurrencyConflictError,
    DuplicateKeyError,
    PersistenceError,
)
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import OP_ID_2, make_operation
from tests.unit.domain.fixtures import LATER, OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_insert_and_get(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
    assert loaded == operation


def test_duplicate_operation_id(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(operation)
    with pytest.raises(DuplicateKeyError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.operations.insert(operation)
    assert exc.value.reason_code == "duplicate_operation_id"


def test_get_missing_returns_none(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(OP_ID) is None


def test_list_by_state(uow_factory: sessionmaker[Session]) -> None:
    pending = make_operation()
    ready = make_operation(operation_id=OP_ID_2, state=OperationState.READY)
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(pending)
        uow.operations.insert(ready)
    with unit_of_work(uow_factory) as uow:
        listed = uow.operations.list_by_state(OperationState.PENDING_POLICY)
    assert [item.operation_id for item in listed] == [OP_ID]


def test_insert_version_not_one_rejected(uow_factory: sessionmaker[Session]) -> None:
    operation = make_operation(version=2)
    with pytest.raises(PersistenceError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.operations.insert(operation)
    assert exc.value.reason_code == "check_violation"


def test_cas_success(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    with unit_of_work(uow_factory) as uow:
        locked = uow.operations.get_for_update(OP_ID)
        assert locked is not None
        updated = replace(
            locked,
            version=2,
            state=OperationState.READY,
            updated_at=LATER,
        )
        uow.operations.update_cas(1, updated)
    with unit_of_work(uow_factory) as uow:
        loaded = uow.operations.get(OP_ID)
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.state is OperationState.READY


def test_cas_stale_version(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    with unit_of_work(uow_factory) as uow:
        locked = uow.operations.get_for_update(OP_ID)
        assert locked is not None
        uow.operations.update_cas(
            1,
            replace(locked, version=2, state=OperationState.READY, updated_at=LATER),
        )
    with pytest.raises(ConcurrencyConflictError):
        with unit_of_work(uow_factory) as uow:
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
        loaded = uow.operations.get(OP_ID)
    assert loaded is not None
    assert loaded.version == 2
    assert loaded.state is OperationState.READY


def test_cas_requires_plus_one(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
    with pytest.raises(ConcurrencyConflictError) as exc:
        with unit_of_work(uow_factory) as uow:
            uow.operations.update_cas(
                1,
                replace(
                    make_operation(),
                    version=3,
                    state=OperationState.READY,
                    updated_at=LATER,
                ),
            )
    assert "expected_version + 1" in str(exc.value)
