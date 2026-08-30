"""Honest capability declarations for the supported GitHub workflow."""

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
EFFECT_CREATE_ISSUE_COMMENT = EffectRef(
    provider=GITHUB_PROVIDER, action="create_issue_comment", version="v1"
)
EFFECT_ADD_LABEL = EffectRef(provider=GITHUB_PROVIDER, action="add_label", version="v1")
EFFECT_CREATE_PULL_REQUEST = EffectRef(
    provider=GITHUB_PROVIDER, action="create_pull_request", version="v1"
)
EFFECT_MERGE_PULL_REQUEST = EffectRef(
    provider=GITHUB_PROVIDER, action="merge_pull_request", version="v1"
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

CREATE_ISSUE_COMMENT_DESCRIPTOR = EffectDescriptor(
    contract_version=CONTRACT_VERSION,
    effect=EFFECT_CREATE_ISSUE_COMMENT,
    mutability=Mutability.MUTATING,
    risk_level=RiskLevel.MODERATE,
    idempotency_mode=IdempotencyMode.NONE,
    verification_mode=VerificationMode.CUSTOM,
    compensation_kind=CompensationKind.NONE,
    supports_external_operation_id=True,
    immediate_response_can_prove_applied=True,
    immediate_response_can_prove_not_applied=True,
    provider_key_semantics=None,
    documentation=(
        "Issue comments have no provider idempotency key. Stateback embeds an "
        "operation marker and can prove presence by direct read or bounded list; "
        "list absence is inconclusive. Deletion is not offered as compensation."
    ),
)

ADD_LABEL_DESCRIPTOR = EffectDescriptor(
    contract_version=CONTRACT_VERSION,
    effect=EFFECT_ADD_LABEL,
    mutability=Mutability.MUTATING,
    risk_level=RiskLevel.LOW,
    idempotency_mode=IdempotencyMode.NATURAL,
    verification_mode=VerificationMode.READ_BACK,
    compensation_kind=CompensationKind.NONE,
    supports_external_operation_id=False,
    immediate_response_can_prove_applied=True,
    immediate_response_can_prove_not_applied=True,
    provider_key_semantics=None,
    documentation=(
        "Adding the same label converges on label presence. Stateback reads issue "
        "labels to verify it. Removal is not compensation because the label may "
        "have pre-existed this operation."
    ),
)

CREATE_PULL_REQUEST_DESCRIPTOR = EffectDescriptor(
    contract_version=CONTRACT_VERSION,
    effect=EFFECT_CREATE_PULL_REQUEST,
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
        "Pull-request creation has no provider idempotency key. Marker and "
        "head/base evidence support positive verification; absence is "
        "inconclusive. Closing a known PR is mitigating, not rollback."
    ),
)

MERGE_PULL_REQUEST_DESCRIPTOR = EffectDescriptor(
    contract_version=CONTRACT_VERSION,
    effect=EFFECT_MERGE_PULL_REQUEST,
    mutability=Mutability.MUTATING,
    risk_level=RiskLevel.HIGH,
    idempotency_mode=IdempotencyMode.NONE,
    verification_mode=VerificationMode.READ_BACK,
    compensation_kind=CompensationKind.NONE,
    supports_external_operation_id=True,
    immediate_response_can_prove_applied=True,
    immediate_response_can_prove_not_applied=True,
    provider_key_semantics=None,
    documentation=(
        "Merge binds the expected head SHA in the provider request and verifies "
        "the same head. A merge cannot be generically reversed and always remains "
        "subject to Stateback policy approval."
    ),
)

GITHUB_DESCRIPTORS = {
    descriptor.effect: descriptor
    for descriptor in (
        CREATE_ISSUE_DESCRIPTOR,
        CREATE_ISSUE_COMMENT_DESCRIPTOR,
        ADD_LABEL_DESCRIPTOR,
        CREATE_PULL_REQUEST_DESCRIPTOR,
        MERGE_PULL_REQUEST_DESCRIPTOR,
    )
}
GITHUB_EFFECTS = tuple(GITHUB_DESCRIPTORS)
