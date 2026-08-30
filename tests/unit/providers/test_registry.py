from __future__ import annotations

import pytest

from stateback.domain.capability import (
    CompensationEvidence,
    CompensationRequest,
    EffectDescriptor,
    ExecutionEvidence,
    ProviderExecutionContext,
    ProviderExecutionRequest,
    ValidationResult,
    VerificationEvidence,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest
from stateback.providers.exceptions import (
    DuplicateEffectRegistrationError,
    UnsupportedEffectError,
)
from stateback.providers.reference.effects import REFERENCE_EFFECTS
from stateback.providers.registry import CapabilityRegistry
from tests.unit.providers.fixtures import make_adapter

pytestmark = pytest.mark.unit

_UNKNOWN = EffectRef(provider="other", action="nope", version="v1")


class _EmptyAdapter:
    def supported_effects(self) -> tuple[EffectRef, ...]:
        return ()

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        raise UnsupportedEffectError(effect)

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        return ValidationResult(accepted=True, error=None)

    def verification_resource_ids(
        self, request: ProviderExecutionRequest
    ) -> tuple[str, ...]:
        del request
        return ()

    def execute(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence:
        raise UnsupportedEffectError(request.effect)

    def verify(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence:
        raise UnsupportedEffectError(request.effect)

    def compensate(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence:
        raise UnsupportedEffectError(
            EffectRef(provider="empty", action="none", version="v1")
        )


def test_register_lists_all_reference_effects() -> None:
    adapter, _, _ = make_adapter()
    registry = CapabilityRegistry()
    registry.register(adapter)
    assert registry.listed_effects() == REFERENCE_EFFECTS


def test_duplicate_effect_registration_rejected() -> None:
    first, _, _ = make_adapter()
    second, _, _ = make_adapter()
    registry = CapabilityRegistry()
    registry.register(first)
    with pytest.raises(DuplicateEffectRegistrationError) as exc:
        registry.register(second)
    assert exc.value.effect == REFERENCE_EFFECTS[0]


def test_unknown_effect_raises_unsupported() -> None:
    adapter, _, _ = make_adapter()
    registry = CapabilityRegistry()
    registry.register(adapter)
    with pytest.raises(UnsupportedEffectError) as exc:
        registry.adapter_for(_UNKNOWN)
    assert exc.value.effect == _UNKNOWN


def test_descriptor_matches_adapter() -> None:
    adapter, _, _ = make_adapter()
    registry = CapabilityRegistry()
    registry.register(adapter)
    effect = REFERENCE_EFFECTS[0]
    assert registry.descriptor(effect) == adapter.descriptor(effect)


def test_empty_adapter_rejected() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(ContractValidationError) as exc:
        registry.register(_EmptyAdapter())
    assert exc.value.reason_code == "empty_string"
