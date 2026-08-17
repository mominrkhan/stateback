from __future__ import annotations

from dataclasses import replace

import pytest

from stateback.compensation.outcome import decide_compensate_kind
from stateback.domain.enums import EffectOutcome
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind
from tests.unit.compensation.fixtures import obligations_with

pytestmark = pytest.mark.unit

_DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY]


def test_unknown_never_applied() -> None:
    decision = decide_compensate_kind(
        outcome=EffectOutcome.UNKNOWN,
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
    )
    assert decision.kind is TransitionKind.COMPENSATION_OUTCOME_UNKNOWN


def test_unknown_never_start_verification() -> None:
    decision = decide_compensate_kind(
        outcome=EffectOutcome.UNKNOWN,
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(require_verification=True),
    )
    assert decision.kind is not CompensationProgressKind.START_COMPENSATION_VERIFICATION
    assert decision.kind is TransitionKind.COMPENSATION_OUTCOME_UNKNOWN


def test_applied_require_verification() -> None:
    decision = decide_compensate_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(require_verification=True),
    )
    assert decision.kind is CompensationProgressKind.START_COMPENSATION_VERIFICATION


def test_applied_immediate_success() -> None:
    assert _DESCRIPTOR.immediate_response_can_prove_applied is True
    decision = decide_compensate_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(require_verification=False),
    )
    assert decision.kind is TransitionKind.COMPENSATION_APPLIED


def test_applied_start_verification_when_descriptor_cannot_prove() -> None:
    descriptor = replace(_DESCRIPTOR, immediate_response_can_prove_applied=False)
    decision = decide_compensate_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=descriptor,
        obligations=obligations_with(require_verification=False),
    )
    assert decision.kind is CompensationProgressKind.START_COMPENSATION_VERIFICATION


def test_not_applied_maps_to_failed() -> None:
    decision = decide_compensate_kind(
        outcome=EffectOutcome.NOT_APPLIED,
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
    )
    assert decision.kind is TransitionKind.COMPENSATION_OUTCOME_FAILED
