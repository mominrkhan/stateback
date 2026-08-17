from __future__ import annotations

import pytest

from stateback.compensation.eligibility import evaluate_start_eligibility
from stateback.domain.enums import (
    AttemptState,
    CompensationKind,
    EffectOutcome,
    ErrorKind,
    OperationState,
)
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from stateback.transitions.kinds import TransitionKind
from tests.unit.compensation.fixtures import (
    make_error,
    make_execution_attempt,
    make_operation,
    obligations_with,
)

pytestmark = pytest.mark.unit

_DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY]
_NONE_DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_NONE]


def test_none_kind_not_compensatable() -> None:
    assert _NONE_DESCRIPTOR.compensation_kind is CompensationKind.NONE
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.SUCCEEDED),
        descriptor=_NONE_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(),
        automatic=False,
        operator=False,
    )
    assert not decision.allowed
    assert decision.start_kind is None
    assert decision.reason_code == "compensation_kind_none"


def test_automatic_forbidden_when_obligation_false() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.SUCCEEDED),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(automatic_compensation_allowed=False),
        latest_original_attempt=make_execution_attempt(),
        automatic=True,
        operator=False,
    )
    assert not decision.allowed
    assert decision.reason_code == "automatic_compensation_forbidden"


def test_succeeded_allowed_when_automatic_true() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.SUCCEEDED),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(automatic_compensation_allowed=True),
        latest_original_attempt=make_execution_attempt(),
        automatic=True,
        operator=False,
    )
    assert decision.allowed
    assert decision.start_kind is TransitionKind.SUCCEEDED_START_COMPENSATION
    assert decision.reason_code == "accepted"


def test_failed_without_artifact_rejected() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.FAILED),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(
            external_operation_id=None, external_resource_ids=()
        ),
        automatic=False,
        operator=False,
    )
    assert not decision.allowed
    assert decision.reason_code == "failed_without_artifact"


def test_failed_validation_rejected() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.FAILED),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(
            state=AttemptState.COMPLETED,
            outcome=EffectOutcome.NOT_APPLIED,
            external_operation_id="ext-1",
            error=make_error(kind=ErrorKind.VALIDATION, code="ref.validation"),
        ),
        automatic=False,
        operator=False,
    )
    assert not decision.allowed
    assert decision.reason_code == "failed_without_artifact"


def test_failed_with_resource_id_allowed() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.FAILED),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(
            state=AttemptState.COMPLETED,
            outcome=EffectOutcome.NOT_APPLIED,
            external_operation_id=None,
            external_resource_ids=("res-1",),
        ),
        automatic=False,
        operator=False,
    )
    assert decision.allowed
    assert decision.start_kind is TransitionKind.FAILED_START_COMPENSATION
    assert decision.reason_code == "accepted"


def test_manual_intervention_requires_operator() -> None:
    denied = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.MANUAL_INTERVENTION),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(),
        automatic=False,
        operator=False,
    )
    assert not denied.allowed
    assert denied.reason_code == "actor_required"

    allowed = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.MANUAL_INTERVENTION),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=make_execution_attempt(),
        automatic=False,
        operator=True,
    )
    assert allowed.allowed
    assert allowed.start_kind is TransitionKind.MANUAL_START_COMPENSATION


def test_ready_not_eligible() -> None:
    decision = evaluate_start_eligibility(
        operation=make_operation(state=OperationState.READY),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        latest_original_attempt=None,
        automatic=False,
        operator=False,
    )
    assert not decision.allowed
    assert decision.start_kind is None
    assert decision.reason_code == "source_state_mismatch"
