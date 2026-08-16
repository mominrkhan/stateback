from __future__ import annotations

from stateback.domain.enums import (
    CompensationKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.policy.inputs import PolicyInputs
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from tests.unit.domain.fixtures import OP_ID, REQUESTER, TS

CLOCK = FixedClock(TS)
ARGUMENTS = json_from_plain({"resource_id": "res-1"})


def make_policy_inputs(
    *,
    mutability: Mutability = Mutability.MUTATING,
    risk_level: RiskLevel = RiskLevel.HIGH,
) -> PolicyInputs:
    return PolicyInputs(
        operation_id=OP_ID,
        operation_version=1,
        intent_digest="a" * 64,
        requester=REQUESTER,
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        risk_level=risk_level,
        mutability=mutability,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        verification_mode=VerificationMode.OPERATION_LOOKUP,
        compensation_kind=CompensationKind.EXACT,
        metadata=(),
        deployment_environment="phase5",
    )
