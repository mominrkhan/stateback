from __future__ import annotations

import pytest

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    AuditEventType,
    EffectOutcome,
    EvidenceSource,
    OperationState,
)
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.persistence.mapping import (
    attempt_from_row,
    attempt_to_row,
    operation_from_row,
    operation_to_row,
)
from stateback.persistence.types import opaque_to_uuid, uuid_to_opaque
from tests.unit.domain.fixtures import (
    ATTEMPT_ID,
    AUDIT_ID,
    LATER,
    OP_ID,
    REQUESTER,
    RISK,
    TS,
    make_intent,
)

pytestmark = pytest.mark.unit


def _operation() -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=OperationState.PENDING_POLICY,
        version=1,
        intent=make_intent(),
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


def test_operation_row_round_trip() -> None:
    operation = _operation()
    assert operation_from_row(operation_to_row(operation)) == operation


def test_attempt_unknown_outcome_round_trip() -> None:
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
        evidence=ProviderEvidence(
            source=EvidenceSource.EXECUTION_RESPONSE,
            provider="reference",
            observed_at=LATER,
            provider_status=None,
            provider_request_id=None,
            external_operation_id=None,
            external_resource_ids=(),
            evidence_fields=json_from_plain({"observed": "timeout"}),
            raw_reference=None,
        ),
        error=None,
        correlation_id=None,
    )
    restored = attempt_from_row(attempt_to_row(attempt))
    assert restored == attempt
    assert restored.outcome is EffectOutcome.UNKNOWN


def test_audit_transition_requires_states() -> None:
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


def test_opaque_uuid_lowercase() -> None:
    assert uuid_to_opaque(opaque_to_uuid(OP_ID)) == OP_ID
