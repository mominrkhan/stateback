"""Frozen reference effects and capability declarations."""

from __future__ import annotations

from stateback.domain.capability import EffectDescriptor, ProviderKeySemantics
from stateback.domain.enums import (
    CONTRACT_VERSION,
    CompensationKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.refs import EffectRef

REFERENCE_PROVIDER = "stateback.reference"

EFFECT_MUTATE_PROVIDER_KEY = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="mutate_provider_key",
    version="v1",
)
EFFECT_MUTATE_NATURAL = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="mutate_natural",
    version="v1",
)
EFFECT_MUTATE_NONE = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="mutate_none",
    version="v1",
)
EFFECT_MUTATE_EVENTUAL = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="mutate_eventual",
    version="v1",
)
EFFECT_MUTATE_MITIGATING = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="mutate_mitigating",
    version="v1",
)
EFFECT_READ_RESOURCE = EffectRef(
    provider=REFERENCE_PROVIDER,
    action="read_resource",
    version="v1",
)

REFERENCE_EFFECTS: tuple[EffectRef, ...] = (
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_EVENTUAL,
    EFFECT_MUTATE_MITIGATING,
    EFFECT_READ_RESOURCE,
)

REFERENCE_KEY_SEMANTICS = ProviderKeySemantics(
    scope="account",
    replay_window="86400",
    same_key_same_request_required=True,
    conflicting_request_behavior="reject",
    response_replay_behavior="replay_original_result",
)


def _descriptor(
    *,
    effect: EffectRef,
    mutability: Mutability,
    risk_level: RiskLevel,
    idempotency_mode: IdempotencyMode,
    verification_mode: VerificationMode,
    compensation_kind: CompensationKind,
    supports_external_operation_id: bool,
    immediate_response_can_prove_applied: bool,
    immediate_response_can_prove_not_applied: bool,
    documentation: str,
) -> EffectDescriptor:
    return EffectDescriptor(
        contract_version=CONTRACT_VERSION,
        effect=effect,
        mutability=mutability,
        risk_level=risk_level,
        idempotency_mode=idempotency_mode,
        verification_mode=verification_mode,
        compensation_kind=compensation_kind,
        supports_external_operation_id=supports_external_operation_id,
        immediate_response_can_prove_applied=immediate_response_can_prove_applied,
        immediate_response_can_prove_not_applied=immediate_response_can_prove_not_applied,
        provider_key_semantics=(
            REFERENCE_KEY_SEMANTICS
            if idempotency_mode is IdempotencyMode.PROVIDER_KEY
            else None
        ),
        documentation=documentation,
    )


REFERENCE_DESCRIPTORS: dict[EffectRef, EffectDescriptor] = {
    EFFECT_MUTATE_PROVIDER_KEY: _descriptor(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        mutability=Mutability.MUTATING,
        risk_level=RiskLevel.HIGH,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        verification_mode=VerificationMode.OPERATION_LOOKUP,
        compensation_kind=CompensationKind.EXACT,
        supports_external_operation_id=True,
        immediate_response_can_prove_applied=True,
        immediate_response_can_prove_not_applied=True,
        documentation=(
            "Reference mutating effect with provider-native key, "
            "operation lookup, and exact compensation."
        ),
    ),
    EFFECT_MUTATE_NATURAL: _descriptor(
        effect=EFFECT_MUTATE_NATURAL,
        mutability=Mutability.MUTATING,
        risk_level=RiskLevel.MODERATE,
        idempotency_mode=IdempotencyMode.NATURAL,
        verification_mode=VerificationMode.READ_BACK,
        compensation_kind=CompensationKind.APPROXIMATE,
        supports_external_operation_id=False,
        immediate_response_can_prove_applied=True,
        immediate_response_can_prove_not_applied=True,
        documentation=(
            "Reference mutating effect with natural idempotency, "
            "read-back, and approximate compensation."
        ),
    ),
    EFFECT_MUTATE_NONE: _descriptor(
        effect=EFFECT_MUTATE_NONE,
        mutability=Mutability.MUTATING,
        risk_level=RiskLevel.HIGH,
        idempotency_mode=IdempotencyMode.NONE,
        verification_mode=VerificationMode.NONE,
        compensation_kind=CompensationKind.NONE,
        supports_external_operation_id=False,
        immediate_response_can_prove_applied=True,
        immediate_response_can_prove_not_applied=True,
        documentation=(
            "Reference mutating effect with no idempotency, "
            "verification, or compensation."
        ),
    ),
    EFFECT_MUTATE_EVENTUAL: _descriptor(
        effect=EFFECT_MUTATE_EVENTUAL,
        mutability=Mutability.MUTATING,
        risk_level=RiskLevel.HIGH,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        verification_mode=VerificationMode.READ_BACK,
        compensation_kind=CompensationKind.EXACT,
        supports_external_operation_id=True,
        immediate_response_can_prove_applied=True,
        immediate_response_can_prove_not_applied=False,
        documentation=(
            "Reference mutating effect whose read-back is eventually "
            "consistent; not-found is not proof."
        ),
    ),
    EFFECT_MUTATE_MITIGATING: _descriptor(
        effect=EFFECT_MUTATE_MITIGATING,
        mutability=Mutability.MUTATING,
        risk_level=RiskLevel.CRITICAL,
        idempotency_mode=IdempotencyMode.PROVIDER_KEY,
        verification_mode=VerificationMode.OPERATION_LOOKUP,
        compensation_kind=CompensationKind.MITIGATING,
        supports_external_operation_id=True,
        immediate_response_can_prove_applied=True,
        immediate_response_can_prove_not_applied=True,
        documentation=(
            "Reference mutating effect whose compensation mitigates harm "
            "without restoring prior state."
        ),
    ),
    EFFECT_READ_RESOURCE: _descriptor(
        effect=EFFECT_READ_RESOURCE,
        mutability=Mutability.READ_ONLY,
        risk_level=RiskLevel.LOW,
        idempotency_mode=IdempotencyMode.NATURAL,
        verification_mode=VerificationMode.READ_BACK,
        compensation_kind=CompensationKind.NONE,
        supports_external_operation_id=False,
        immediate_response_can_prove_applied=False,
        immediate_response_can_prove_not_applied=True,
        documentation=(
            "Reference read-only lookup. Successful execute does not mutate."
        ),
    ),
}
