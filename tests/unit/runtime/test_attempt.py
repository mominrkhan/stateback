from __future__ import annotations

import pytest

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import ExecutionEvidence
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    EffectOutcome,
    OperationState,
)
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.operation import Operation
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from stateback.runtime.attempt import (
    build_completed_attempt,
    build_started_attempt,
    provider_key_for,
)
from tests.unit.domain.fixtures import ATTEMPT_ID, LATER, OP_ID, RISK, TS, make_intent

pytestmark = pytest.mark.unit


def _operation() -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=OperationState.READY,
        version=2,
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


def test_provider_key_uses_operation_idempotency_identity_for_provider_key_mode() -> (
    None
):
    operation = _operation()
    key = provider_key_for(
        operation=operation,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        prior_attempts=(),
    )
    assert key == operation.idempotency_identity


def test_provider_key_none_for_natural_and_none_modes() -> None:
    operation = _operation()
    natural = provider_key_for(
        operation=operation,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_NATURAL],
        prior_attempts=(),
    )
    none = provider_key_for(
        operation=operation,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_NONE],
        prior_attempts=(),
    )
    assert natural is None
    assert none is None


def test_provider_key_reuses_prior_attempt_key() -> None:
    operation = _operation()
    prior = ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=ATTEMPT_ID,
        operation_id=OP_ID,
        attempt_number=1,
        state=AttemptState.COMPLETED,
        started_at=TS,
        completed_at=LATER,
        provider_idempotency_key="prior-key",
        external_operation_id=None,
        external_resource_ids=(),
        outcome=EffectOutcome.NOT_APPLIED,
        evidence=None,
        error=None,
        correlation_id=None,
    )
    key = provider_key_for(
        operation=operation,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_NATURAL],
        prior_attempts=(prior,),
    )
    assert key == "prior-key"


def test_completed_attempt_preserves_ids_and_started_at() -> None:
    started = build_started_attempt(
        operation=_operation(),
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        started_at=TS,
        provider_idempotency_key="k",
        correlation_id="c1",
    )
    evidence = ExecutionEvidence(
        outcome=EffectOutcome.APPLIED,
        evidence=None,
        error=None,
        external_operation_id="ext-1",
        external_resource_ids=("res-1",),
    )
    completed = build_completed_attempt(
        started=started,
        evidence=evidence,
        completed_at=LATER,
    )
    assert completed.attempt_id == started.attempt_id
    assert completed.operation_id == started.operation_id
    assert completed.started_at == started.started_at
    assert completed.attempt_number == started.attempt_number
    assert completed.correlation_id == started.correlation_id
    assert completed.state is AttemptState.COMPLETED
    assert completed.outcome is EffectOutcome.APPLIED
    assert completed.external_operation_id == "ext-1"
