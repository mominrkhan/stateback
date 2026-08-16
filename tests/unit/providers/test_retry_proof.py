from __future__ import annotations

import pytest

from stateback.domain.capability import ProviderKeySemantics
from stateback.domain.enums import EffectOutcome, RetrySafetyVerdict
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
)
from stateback.providers.registry import CapabilityRegistry
from stateback.providers.retry import (
    parse_replay_window_seconds,
    replay_window_has_elapsed,
)
from tests.unit.providers.fixtures import TS, make_adapter

pytestmark = pytest.mark.unit


def _registry() -> CapabilityRegistry:
    adapter, _, _ = make_adapter()
    registry = CapabilityRegistry()
    registry.register(adapter)
    return registry


def test_registry_provider_key_inside_window_safe() -> None:
    decision = _registry().evaluate_retry_safety(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        now=TS,
        first_attempt_at=TS,
    )
    assert decision.verdict is RetrySafetyVerdict.SAFE
    assert decision.reason_code == "provider_key_within_replay_window"


def test_registry_provider_key_after_86400_seconds_unsafe() -> None:
    adapter, _, clock = make_adapter()
    registry = CapabilityRegistry()
    registry.register(adapter)
    clock.advance(86400)
    decision = registry.evaluate_retry_safety(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        now=clock.now(),
        first_attempt_at=TS,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "provider_key_replay_window_elapsed"


def test_registry_provider_key_without_first_attempt_unsafe() -> None:
    decision = _registry().evaluate_retry_safety(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        now=TS,
        first_attempt_at=None,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "provider_key_replay_window_unknown_start"


def test_registry_natural_registered_is_safe() -> None:
    decision = _registry().evaluate_retry_safety(
        effect=EFFECT_MUTATE_NATURAL,
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        now=TS,
    )
    assert decision.verdict is RetrySafetyVerdict.SAFE
    assert decision.reason_code == "natural_idempotency_tested_declaration"


def test_registry_none_unknown_is_unsafe() -> None:
    decision = _registry().evaluate_retry_safety(
        effect=EFFECT_MUTATE_NONE,
        execution_outcome=EffectOutcome.UNKNOWN,
        verification_outcome=None,
        now=TS,
    )
    assert decision.verdict is RetrySafetyVerdict.UNSAFE
    assert decision.reason_code == "unknown_without_idempotency"


def test_parse_replay_window_seconds_86400() -> None:
    assert parse_replay_window_seconds("86400") == 86400
    assert parse_replay_window_seconds(None) is None


def test_unparseable_replay_window_is_elapsed() -> None:
    semantics = ProviderKeySemantics(
        scope="account",
        replay_window="24h",
        same_key_same_request_required=True,
        conflicting_request_behavior="reject",
        response_replay_behavior="replay_original_result",
    )
    assert replay_window_has_elapsed(semantics=semantics, started_at=TS, now=TS) is True
