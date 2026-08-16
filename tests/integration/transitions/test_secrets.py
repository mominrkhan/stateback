from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import AuditEventType, OperationState
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_from_plain
from stateback.persistence.uow import UnitOfWork, unit_of_work
from stateback.transitions.audit import build_audit_event
from stateback.transitions.kinds import TransitionKind
from tests.integration.transitions.conftest import prepare_source
from tests.unit.domain.fixtures import AUDIT_ID, LATER, OP_ID, REQUESTER

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_audit_data_with_token_rejected(uow_factory: sessionmaker[Session]) -> None:
    with pytest.raises(ContractValidationError) as exc:
        build_audit_event(
            audit_event_id=AUDIT_ID,
            operation_id=OP_ID,
            sequence=1,
            event_type=AuditEventType.OPERATION_CREATED,
            from_state=None,
            to_state=OperationState.PENDING_POLICY,
            operation_version=1,
            actor=REQUESTER,
            reason_code="created",
            data=json_from_plain({"access_token": "secret-value"}),
            correlation_id=None,
            created_at=LATER,
        )
    assert exc.value.reason_code == "secret_field"

    scenario = prepare_source(uow_factory, TransitionKind.CREATE_OPERATION)
    uow = UnitOfWork(uow_factory())
    try:
        from stateback.transitions.service import TransitionService
        from tests.integration.transitions.conftest import command_for

        result = TransitionService().apply(
            uow, command_for(scenario, TransitionKind.CREATE_OPERATION)
        )
        assert result.operation is not None
        with pytest.raises(ContractValidationError):
            uow.audit_events.append(
                build_audit_event(
                    audit_event_id=scenario.ids.next(),
                    operation_id=result.operation.operation_id,
                    sequence=2,
                    event_type=AuditEventType.OPERATOR_ACTION,
                    from_state=None,
                    to_state=None,
                    operation_version=1,
                    actor=REQUESTER,
                    reason_code="leak",
                    data=json_from_plain({"token": "leak"}),
                    correlation_id=None,
                    created_at=LATER,
                )
            )
        uow.rollback()
    finally:
        uow.close()
    with unit_of_work(uow_factory) as reload:
        assert reload.operations.get(OP_ID) is None
