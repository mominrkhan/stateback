from __future__ import annotations

import pytest

from stateback.domain.capability import ProviderKeySemantics
from stateback.domain.enums import (
    EffectOutcome,
    IdempotencyMode,
    RetrySafetyVerdict,
)
from stateback.domain.retry_safety import evaluate_effect_retry_safety

pytestmark = pytest.mark.unit


def test_unknown_without_idempotency_is_unsafe() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.NONE,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "unknown_without_idempotency"


def test_timeout_only_is_not_a_safety_basis() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.NONE,
        insufficient_signal="timeout_only",
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "timeout_only"


def test_retryable_infrastructure_flag_is_not_effect_retry() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        insufficient_signal="retryable_infrastructure_flag",
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE


def test_verified_not_applied_is_safe() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=EffectOutcome.NOT_APPLIED,
        idempotency_mode=IdempotencyMode.NONE,
    )
    assert decision.verdict is RetrySafetyVerdict.SAFE


def test_provider_key_needs_capability_proof() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
    )
    assert decision.verdict is RetrySafetyVerdict.NEEDS_CAPABILITY_PROOF


def test_applied_is_not_retryable() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.APPLIED,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.NATURAL,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "already_applied"


def test_provider_key_with_semantics_inside_window_is_safe() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        provider_key_semantics=ProviderKeySemantics(
            scope="account",
            replay_window="86400",
            same_key_same_request_required=True,
            conflicting_request_behavior="reject",
            response_replay_behavior="replay_original_result",
        ),
        replay_window_elapsed=False,
    )
    assert decision.verdict is RetrySafetyVerdict.SAFE
    assert decision.reason_code == "provider_key_within_replay_window"


def test_provider_key_with_semantics_elapsed_window_is_unsafe() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        provider_key_semantics=ProviderKeySemantics(
            scope="account",
            replay_window="86400",
            same_key_same_request_required=True,
            conflicting_request_behavior="reject",
            response_replay_behavior="replay_original_result",
        ),
        replay_window_elapsed=True,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "provider_key_replay_window_elapsed"


def test_natural_tested_declaration_is_safe() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.NATURAL,
        natural_declaration_tested=True,
    )
    assert decision.verdict is RetrySafetyVerdict.SAFE
    assert decision.reason_code == "natural_idempotency_tested_declaration"


def test_natural_untested_still_needs_proof() -> None:
    decision = evaluate_effect_retry_safety(
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        idempotency_mode=IdempotencyMode.NATURAL,
        natural_declaration_tested=False,
    )
    assert decision.verdict is RetrySafetyVerdict.NEEDS_CAPABILITY_PROOF
    assert decision.reason_code == "natural_idempotency_requires_tested_declaration"
