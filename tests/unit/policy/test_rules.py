from __future__ import annotations

import pytest

from stateback.domain.enums import PolicyVerdict, PrincipalType, RiskLevel
from stateback.domain.exceptions import ContractValidationError
from stateback.policy import PHASE5_DEFAULT_OBLIGATIONS, PolicyRule, RulePolicyEngine
from tests.unit.runtime.fixtures import make_policy_inputs

pytestmark = pytest.mark.unit


def test_first_matching_rule_is_deterministic() -> None:
    engine = RulePolicyEngine(
        policy_revision="org-policy-7",
        rules=(
            PolicyRule(
                rule_id="critical-needs-review",
                verdict=PolicyVerdict.REQUIRE_APPROVAL,
                obligations=PHASE5_DEFAULT_OBLIGATIONS,
                risk_levels=frozenset({RiskLevel.CRITICAL}),
            ),
            PolicyRule(
                rule_id="agents-allowed",
                verdict=PolicyVerdict.ALLOW,
                obligations=PHASE5_DEFAULT_OBLIGATIONS,
                requester_types=frozenset({PrincipalType.AGENT}),
            ),
        ),
        default_obligations=PHASE5_DEFAULT_OBLIGATIONS,
    )
    inputs = make_policy_inputs(risk_level=RiskLevel.CRITICAL)
    first = engine.evaluate(inputs)
    second = engine.evaluate(inputs)
    assert first == second
    assert first.verdict is PolicyVerdict.REQUIRE_APPROVAL
    assert first.reason_codes == ("policy.rule.critical-needs-review",)
    assert first.policy_revision == "org-policy-7"


def test_no_matching_rule_fails_closed() -> None:
    engine = RulePolicyEngine(
        policy_revision="org-policy-8",
        rules=(),
        default_obligations=PHASE5_DEFAULT_OBLIGATIONS,
    )
    evaluation = engine.evaluate(make_policy_inputs())
    assert evaluation.verdict is PolicyVerdict.DENY
    assert evaluation.reason_codes == ("policy.default_deny",)


def test_duplicate_rule_ids_are_rejected() -> None:
    rule = PolicyRule(
        rule_id="same",
        verdict=PolicyVerdict.DENY,
        obligations=PHASE5_DEFAULT_OBLIGATIONS,
    )
    with pytest.raises(ContractValidationError):
        RulePolicyEngine(
            policy_revision="org-policy-9",
            rules=(rule, rule),
            default_obligations=PHASE5_DEFAULT_OBLIGATIONS,
        )
