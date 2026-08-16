from __future__ import annotations

import pytest

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    EffectOutcome,
    ErrorKind,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.serde import dumps_wire, loads_wire
from tests.unit.domain.fixtures import ATTEMPT_ID, LATER, OP_ID, TS

pytestmark = pytest.mark.unit


def _started() -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=ATTEMPT_ID,
        operation_id=OP_ID,
        attempt_number=1,
        state=AttemptState.STARTED,
        started_at=TS,
        completed_at=None,
        provider_idempotency_key=None,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=None,
        evidence=None,
        error=None,
        correlation_id=None,
    )


def test_started_attempt_cannot_have_outcome() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ExecutionAttempt(
            contract_version=CONTRACT_VERSION,
            attempt_id=ATTEMPT_ID,
            operation_id=OP_ID,
            attempt_number=1,
            state=AttemptState.STARTED,
            started_at=TS,
            completed_at=None,
            provider_idempotency_key=None,
            external_operation_id=None,
            external_resource_ids=(),
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=None,
            error=None,
            correlation_id=None,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_completed_attempt_requires_outcome() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ExecutionAttempt(
            contract_version=CONTRACT_VERSION,
            attempt_id=ATTEMPT_ID,
            operation_id=OP_ID,
            attempt_number=1,
            state=AttemptState.COMPLETED,
            started_at=TS,
            completed_at=LATER,
            provider_idempotency_key=None,
            external_operation_id=None,
            external_resource_ids=(),
            outcome=None,
            evidence=None,
            error=None,
            correlation_id=None,
        )
    assert exc.value.reason_code == "illegal_combination"


def test_unknown_outcome_round_trips_distinct_from_failed() -> None:
    attempt = ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=ATTEMPT_ID,
        operation_id=OP_ID,
        attempt_number=1,
        state=AttemptState.COMPLETED,
        started_at=TS,
        completed_at=LATER,
        provider_idempotency_key=None,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=EffectOutcome.UNKNOWN,
        evidence=None,
        error=NormalizedError(
            contract_version=CONTRACT_VERSION,
            kind=ErrorKind.TRANSIENT_TRANSPORT,
            code="stateback.transient_transport.timeout",
            message="timeout after possible transmission",
            retryable_infrastructure=True,
            provider_http_status=None,
            provider_error_code=None,
            retry_after_seconds=None,
            details=json_from_plain({}),
        ),
        correlation_id=None,
    )
    restored = loads_wire(dumps_wire(attempt.to_wire()), ExecutionAttempt.from_wire)
    assert restored.outcome is EffectOutcome.UNKNOWN
    assert restored.error is not None
    assert restored.error.retryable_infrastructure is True


def test_started_round_trip() -> None:
    restored = loads_wire(dumps_wire(_started().to_wire()), ExecutionAttempt.from_wire)
    assert restored.state is AttemptState.STARTED
    assert restored.outcome is None
