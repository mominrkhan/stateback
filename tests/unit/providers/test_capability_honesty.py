from __future__ import annotations

import pytest

from stateback.domain.enums import (
    CompensationKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.refs import EffectRef
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_EVENTUAL,
    EFFECT_MUTATE_MITIGATING,
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_READ_RESOURCE,
    REFERENCE_DESCRIPTORS,
    REFERENCE_EFFECTS,
    REFERENCE_KEY_SEMANTICS,
)
from tests.unit.providers.fixtures import (
    make_adapter,
    make_compensate_request,
    make_context,
    make_request,
    make_verify_request,
)

pytestmark = pytest.mark.unit

_EXPECTED: dict[EffectRef, tuple[object, ...]] = {
    EFFECT_MUTATE_PROVIDER_KEY: (
        Mutability.MUTATING,
        RiskLevel.HIGH,
        IdempotencyMode.PROVIDER_KEY,
        VerificationMode.OPERATION_LOOKUP,
        CompensationKind.EXACT,
        True,
        True,
        True,
        "Reference mutating effect with provider-native key, operation lookup, and exact compensation.",
    ),
    EFFECT_MUTATE_NATURAL: (
        Mutability.MUTATING,
        RiskLevel.MODERATE,
        IdempotencyMode.NATURAL,
        VerificationMode.READ_BACK,
        CompensationKind.APPROXIMATE,
        False,
        True,
        True,
        "Reference mutating effect with natural idempotency, read-back, and approximate compensation.",
    ),
    EFFECT_MUTATE_NONE: (
        Mutability.MUTATING,
        RiskLevel.HIGH,
        IdempotencyMode.NONE,
        VerificationMode.NONE,
        CompensationKind.NONE,
        False,
        True,
        True,
        "Reference mutating effect with no idempotency, verification, or compensation.",
    ),
    EFFECT_MUTATE_EVENTUAL: (
        Mutability.MUTATING,
        RiskLevel.HIGH,
        IdempotencyMode.PROVIDER_KEY,
        VerificationMode.READ_BACK,
        CompensationKind.EXACT,
        True,
        True,
        False,
        "Reference mutating effect whose read-back is eventually consistent; not-found is not proof.",
    ),
    EFFECT_MUTATE_MITIGATING: (
        Mutability.MUTATING,
        RiskLevel.CRITICAL,
        IdempotencyMode.PROVIDER_KEY,
        VerificationMode.OPERATION_LOOKUP,
        CompensationKind.MITIGATING,
        True,
        True,
        True,
        "Reference mutating effect whose compensation mitigates harm without restoring prior state.",
    ),
    EFFECT_READ_RESOURCE: (
        Mutability.READ_ONLY,
        RiskLevel.LOW,
        IdempotencyMode.NATURAL,
        VerificationMode.READ_BACK,
        CompensationKind.NONE,
        False,
        False,
        True,
        "Reference read-only lookup. Successful execute does not mutate.",
    ),
}


@pytest.mark.parametrize("effect", REFERENCE_EFFECTS)
def test_every_reference_descriptor_matches_effects_table(effect: EffectRef) -> None:
    desc = REFERENCE_DESCRIPTORS[effect]
    expected = _EXPECTED[effect]
    assert desc.effect == effect
    assert desc.mutability is expected[0]
    assert desc.risk_level is expected[1]
    assert desc.idempotency_mode is expected[2]
    assert desc.verification_mode is expected[3]
    assert desc.compensation_kind is expected[4]
    assert desc.supports_external_operation_id is expected[5]
    assert desc.immediate_response_can_prove_applied is expected[6]
    assert desc.immediate_response_can_prove_not_applied is expected[7]
    assert desc.documentation == expected[8]
    if desc.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
        assert desc.provider_key_semantics == REFERENCE_KEY_SEMANTICS
    else:
        assert desc.provider_key_semantics is None


def test_provider_key_effects_require_key_semantics() -> None:
    for effect in REFERENCE_EFFECTS:
        desc = REFERENCE_DESCRIPTORS[effect]
        if desc.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
            assert desc.provider_key_semantics is not None


def test_read_only_compensation_is_none() -> None:
    desc = REFERENCE_DESCRIPTORS[EFFECT_READ_RESOURCE]
    assert desc.mutability is Mutability.READ_ONLY
    assert desc.compensation_kind is CompensationKind.NONE


def test_mutate_none_verify_returns_unsupported() -> None:
    adapter, _, _ = make_adapter()
    evidence = adapter.verify(make_context(), make_verify_request(EFFECT_MUTATE_NONE))
    assert evidence.error is not None
    assert evidence.error.code == "ref.unsupported.verification"


def test_mutate_none_compensate_returns_unsupported() -> None:
    adapter, _, _ = make_adapter()
    adapter.execute(make_context(effect_key=None), make_request(EFFECT_MUTATE_NONE))
    evidence = adapter.compensate(
        make_context(),
        make_compensate_request(provider_idempotency_key=None),
    )
    assert evidence.error is not None
    assert evidence.error.code == "ref.unsupported.compensation"


def test_immediate_not_applied_claim_matches_eventual_false() -> None:
    desc = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_EVENTUAL]
    assert desc.immediate_response_can_prove_not_applied is False
