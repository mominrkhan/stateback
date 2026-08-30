from __future__ import annotations

import threading

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
from stateback.providers.reference.adapter import ReferenceAdapter


class BlockingAdapter:
    def __init__(self, inner: ReferenceAdapter, gate: threading.Event) -> None:
        self._inner = inner
        self._gate = gate

    def supported_effects(self) -> tuple[EffectRef, ...]:
        return self._inner.supported_effects()

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        return self._inner.descriptor(effect)

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        return self._inner.validate_execution(request)

    def verification_resource_ids(
        self, request: ProviderExecutionRequest
    ) -> tuple[str, ...]:
        return self._inner.verification_resource_ids(request)

    def execute(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence:
        self._gate.wait()
        return self._inner.execute(context, request)

    def verify(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence:
        return self._inner.verify(context, request)

    def compensate(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence:
        return self._inner.compensate(context, request)
