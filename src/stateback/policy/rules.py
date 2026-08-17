"""Deterministic deployment policy rules with a fail-closed default."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import PolicyVerdict, PrincipalType, RiskLevel
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.policy import PolicyObligations
from stateback.policy.evaluation import PolicyEvaluation
from stateback.policy.inputs import PolicyInputs


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRule:
    rule_id: str
    verdict: PolicyVerdict
    obligations: PolicyObligations
    explanation: str | None = None
    providers: frozenset[str] = frozenset()
    actions: frozenset[str] = frozenset()
    versions: frozenset[str] = frozenset()
    risk_levels: frozenset[RiskLevel] = frozenset()
    requester_types: frozenset[PrincipalType] = frozenset()
    deployment_environments: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.rule_id or self.rule_id.strip() != self.rule_id:
            raise ContractValidationError(
                "invalid_policy_rule", "rule_id must be non-empty and trimmed"
            )

    def matches(self, inputs: PolicyInputs) -> bool:
        return (
            (not self.providers or inputs.effect.provider in self.providers)
            and (not self.actions or inputs.effect.action in self.actions)
            and (not self.versions or inputs.effect.version in self.versions)
            and (not self.risk_levels or inputs.risk_level in self.risk_levels)
            and (
                not self.requester_types
                or inputs.requester.type in self.requester_types
            )
            and (
                not self.deployment_environments
                or inputs.deployment_environment in self.deployment_environments
            )
        )


class RulePolicyEngine:
    def __init__(
        self,
        *,
        policy_revision: str,
        rules: tuple[PolicyRule, ...],
        default_obligations: PolicyObligations,
    ) -> None:
        if not policy_revision or policy_revision.strip() != policy_revision:
            raise ContractValidationError(
                "invalid_policy_revision",
                "policy_revision must be non-empty and trimmed",
            )
        rule_ids = tuple(rule.rule_id for rule in rules)
        if len(rule_ids) != len(set(rule_ids)):
            raise ContractValidationError(
                "duplicate_policy_rule", "policy rule IDs must be unique"
            )
        self._revision = policy_revision
        self._rules = rules
        self._default_obligations = default_obligations

    def evaluate(self, inputs: PolicyInputs) -> PolicyEvaluation:
        for rule in self._rules:
            if rule.matches(inputs):
                return PolicyEvaluation(
                    verdict=rule.verdict,
                    reason_codes=(f"policy.rule.{rule.rule_id}",),
                    explanation=rule.explanation,
                    obligations=rule.obligations,
                    policy_revision=self._revision,
                )
        return PolicyEvaluation(
            verdict=PolicyVerdict.DENY,
            reason_codes=("policy.default_deny",),
            explanation="No configured policy rule authorized this operation",
            obligations=self._default_obligations,
            policy_revision=self._revision,
        )
