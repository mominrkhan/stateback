from __future__ import annotations

import dataclasses

import pytest

from stateback.domain.enums import EffectOutcome, RetrySafetyVerdict
from stateback.domain.policy import PolicyObligations
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_READ_RESOURCE,
    REFERENCE_DESCRIPTORS,
)
from stateback.runtime.outcome import decide_execution_kind, max_automatic_attempts
from stateback.transitions.kinds import TransitionKind

pytestmark = pytest.mark.unit

_DEFAULT = PolicyObligations(
    require_verification=False,
    max_automatic_execution_attempts=1,
    max_automatic_recovery_attempts=None,
    automatic_compensation_allowed=False,
    operator_reason_required=False,
    approval_expires_at=None,
)


def test_unknown_always_execution_unknown() -> None:
    decision = decide_execution_kind(
        outcome=EffectOutcome.UNKNOWN,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=_DEFAULT,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.SAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_UNKNOWN
    assert decision.reason_code == "execution_unknown"


def test_applied_without_verification_obligation_is_execution_applied() -> None:
    decision = decide_execution_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=_DEFAULT,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.UNSAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_APPLIED


def test_applied_with_require_verification_is_require_verification() -> None:
    obligations = dataclasses.replace(_DEFAULT, require_verification=True)
    decision = decide_execution_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=obligations,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.UNSAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_REQUIRE_VERIFICATION


def test_applied_when_immediate_response_cannot_prove_applied_is_require_verification() -> (
    None
):
    decision = decide_execution_kind(
        outcome=EffectOutcome.APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_READ_RESOURCE],
        obligations=_DEFAULT,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.UNSAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_REQUIRE_VERIFICATION


def test_not_applied_safe_under_cap_is_retry() -> None:
    obligations = dataclasses.replace(_DEFAULT, max_automatic_execution_attempts=2)
    decision = decide_execution_kind(
        outcome=EffectOutcome.NOT_APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=obligations,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.SAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_NOT_APPLIED_RETRY


def test_not_applied_safe_at_cap_is_fail() -> None:
    decision = decide_execution_kind(
        outcome=EffectOutcome.NOT_APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=_DEFAULT,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.SAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_NOT_APPLIED_FAIL


def test_not_applied_unsafe_is_fail() -> None:
    obligations = dataclasses.replace(_DEFAULT, max_automatic_execution_attempts=5)
    decision = decide_execution_kind(
        outcome=EffectOutcome.NOT_APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=obligations,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.UNSAFE,
    )
    assert decision.kind is TransitionKind.EXECUTION_NOT_APPLIED_FAIL


def test_max_automatic_attempts_none_or_less_than_one_is_one() -> None:
    none_cap = dataclasses.replace(_DEFAULT, max_automatic_execution_attempts=None)
    zero_cap = dataclasses.replace(_DEFAULT, max_automatic_execution_attempts=0)
    assert max_automatic_attempts(none_cap) == 1
    assert max_automatic_attempts(zero_cap) == 1
