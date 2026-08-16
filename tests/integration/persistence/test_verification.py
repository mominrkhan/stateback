from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import EffectOutcome, ReconciliationAction
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.persistence.types import StoredReconciliationDecision
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import (
    RECONCILE_ID,
    make_operation,
    make_started_attempt,
    make_verification_request,
    make_verification_result,
)
from tests.unit.domain.fixtures import LATER, OP_ID, TS, VERIFY_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_insert_request_without_result(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.attempts.insert(make_started_attempt())
        uow.verifications.insert_request(make_verification_request())
    with unit_of_work(uow_factory) as uow:
        loaded = uow.verifications.get(VERIFY_ID)
    assert loaded is not None
    request, result = loaded
    assert request.verification_id == VERIFY_ID
    assert result is None


def test_complete_result_unknown(uow_factory: sessionmaker[Session]) -> None:
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.attempts.insert(make_started_attempt())
        uow.verifications.insert_request(make_verification_request())
        uow.verifications.complete(make_verification_result())
    with unit_of_work(uow_factory) as uow:
        loaded = uow.verifications.get(VERIFY_ID)
    assert loaded is not None
    _, result = loaded
    assert result is not None
    assert result.outcome is EffectOutcome.UNKNOWN


def test_reconciliation_insert_and_list(uow_factory: sessionmaker[Session]) -> None:
    request = make_verification_request()
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(make_operation())
        uow.attempts.insert(make_started_attempt())
        uow.verifications.insert_request(request)
        uow.verifications.complete(make_verification_result())
        uow.reconciliation_decisions.insert(
            StoredReconciliationDecision(
                reconciliation_decision_id=RECONCILE_ID,
                operation_id=OP_ID,
                operation_version=1,
                verification_id=VERIFY_ID,
                decision=ReconciliationDecision(
                    action=ReconciliationAction.REMAIN_UNKNOWN,
                    reason_code="still_unknown",
                ),
                created_at=TS,
            )
        )
    with unit_of_work(uow_factory) as uow:
        stored = uow.reconciliation_decisions.list_for_operation(OP_ID)
        verification = uow.verifications.get(VERIFY_ID)
    assert len(stored) == 1
    assert stored[0].decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert verification is not None
    _, result = verification
    assert result is not None
    assert result.completed_at == LATER
