"""Provider adapter protocol — evidence in, no lifecycle mutation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest


@runtime_checkable
class ProviderAdapter(Protocol):
    def supported_effects(self) -> tuple[EffectRef, ...]: ...

    def descriptor(self, effect: EffectRef) -> EffectDescriptor: ...

    def validate_execution(
        self, request: ProviderExecutionRequest
    ) -> ValidationResult: ...

    def verification_resource_ids(
        self, request: ProviderExecutionRequest
    ) -> tuple[str, ...]: ...

    def execute(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence: ...

    def verify(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence: ...

    def compensate(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence: ...
