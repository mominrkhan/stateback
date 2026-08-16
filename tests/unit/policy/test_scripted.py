from __future__ import annotations

import pytest

from stateback.domain.enums import PolicyVerdict
from stateback.policy import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
    PolicyEvaluation,
    ScriptedPolicyEngine,
)
from tests.unit.runtime.fixtures import make_policy_inputs

pytestmark = pytest.mark.unit


def _evaluation(verdict: PolicyVerdict) -> PolicyEvaluation:
    return PolicyEvaluation(
        verdict=verdict,
        reason_codes=(verdict.value.lower(),),
        explanation=None,
        obligations=PHASE5_DEFAULT_OBLIGATIONS,
        policy_revision=PHASE5_POLICY_REVISION,
    )


def test_scripted_fifo_then_default_allow() -> None:
    engine = ScriptedPolicyEngine()
    engine.enqueue(_evaluation(PolicyVerdict.DENY))
    engine.enqueue(_evaluation(PolicyVerdict.REQUIRE_APPROVAL))
    first = engine.evaluate(make_policy_inputs())
    second = engine.evaluate(make_policy_inputs())
    third = engine.evaluate(make_policy_inputs())
    assert first.verdict is PolicyVerdict.DENY
    assert second.verdict is PolicyVerdict.REQUIRE_APPROVAL
    assert third.verdict is PolicyVerdict.ALLOW


def test_scripted_can_enqueue_deny() -> None:
    engine = ScriptedPolicyEngine()
    engine.enqueue(_evaluation(PolicyVerdict.DENY))
    assert engine.evaluate(make_policy_inputs()).verdict is PolicyVerdict.DENY


def test_scripted_can_enqueue_require_approval() -> None:
    engine = ScriptedPolicyEngine()
    engine.enqueue(_evaluation(PolicyVerdict.REQUIRE_APPROVAL))
    assert (
        engine.evaluate(make_policy_inputs()).verdict is PolicyVerdict.REQUIRE_APPROVAL
    )
