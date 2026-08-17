"""Honest capability declaration for GitHub issue creation."""

from __future__ import annotations

from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import (
    CONTRACT_VERSION,
    CompensationKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.refs import EffectRef

GITHUB_PROVIDER = "github"
EFFECT_CREATE_ISSUE = EffectRef(
    provider=GITHUB_PROVIDER,
    action="create_issue",
    version="v1",
)

CREATE_ISSUE_DESCRIPTOR = EffectDescriptor(
    contract_version=CONTRACT_VERSION,
    effect=EFFECT_CREATE_ISSUE,
    mutability=Mutability.MUTATING,
    risk_level=RiskLevel.MODERATE,
    idempotency_mode=IdempotencyMode.NONE,
    verification_mode=VerificationMode.CUSTOM,
    compensation_kind=CompensationKind.MITIGATING,
    supports_external_operation_id=True,
    immediate_response_can_prove_applied=True,
    immediate_response_can_prove_not_applied=True,
    provider_key_semantics=None,
    documentation=(
        "GitHub REST create-issue endpoint has no provider idempotency key. "
        "Stateback adds an operation marker for positive search/read-back "
        "verification. Absence is inconclusive. Compensation closes the issue "
        "and is mitigating, not rollback. See "
        "https://docs.github.com/en/rest/issues/issues#create-an-issue"
    ),
)
