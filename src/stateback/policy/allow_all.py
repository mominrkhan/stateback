"""Allow-all policy stub. Not a production authorization policy."""

from __future__ import annotations

from stateback.domain.enums import PolicyVerdict
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
    PolicyEvaluation,
)
from stateback.policy.inputs import PolicyInputs


class AllowAllPolicyEngine:
    def evaluate(self, inputs: PolicyInputs) -> PolicyEvaluation:
        del inputs
        return PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("phase5.allow_all",),
            explanation=(
                "Phase 5 allow-all engine; not a production authorization policy"
            ),
            obligations=PHASE5_DEFAULT_OBLIGATIONS,
            policy_revision=PHASE5_POLICY_REVISION,
        )
