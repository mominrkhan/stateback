"""Local-development-only, operation-scoped lost-response simulation."""

from __future__ import annotations

import stat
from pathlib import Path

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
from stateback.domain.enums import (
    CONTRACT_VERSION,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest
from stateback.providers.github.effects import EFFECT_CREATE_ISSUE
from stateback.providers.protocol import ProviderAdapter
from stateback.runtime.clock import Clock


class OperationScopedLostResponseAdapter:
    """Discard one successful create-issue response for one armed operation."""

    def __init__(
        self, *, delegate: ProviderAdapter, arm_directory: Path, clock: Clock
    ) -> None:
        self._delegate = delegate
        self._arm_directory = arm_directory
        self._clock = clock

    def supported_effects(self) -> tuple[EffectRef, ...]:
        return self._delegate.supported_effects()

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        return self._delegate.descriptor(effect)

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        return self._delegate.validate_execution(request)

    def verification_resource_ids(
        self, request: ProviderExecutionRequest
    ) -> tuple[str, ...]:
        return self._delegate.verification_resource_ids(request)

    def execute(
        self, context: ProviderExecutionContext, request: ProviderExecutionRequest
    ) -> ExecutionEvidence:
        result = self._delegate.execute(context, request)
        if (
            request.effect != EFFECT_CREATE_ISSUE
            or result.outcome is not EffectOutcome.APPLIED
            or not self._consume(context)
        ):
            return result
        evidence = ProviderEvidence(
            source=EvidenceSource.EXECUTION_RESPONSE,
            provider="github",
            observed_at=self._clock.now(),
            provider_status="response_deliberately_lost",
            provider_request_id=None,
            external_operation_id=None,
            external_resource_ids=(),
            evidence_fields=json_from_plain(
                {"development_demo": True, "fault_scope": "operation_id"}
            ),
            raw_reference=None,
        )
        error = NormalizedError(
            contract_version=CONTRACT_VERSION,
            kind=ErrorKind.TRANSIENT_TRANSPORT,
            code="github.demo.response_lost",
            message="github.demo.response_lost",
            retryable_infrastructure=True,
            provider_http_status=None,
            provider_error_code=None,
            retry_after_seconds=None,
            details=json_from_plain({}),
        )
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=evidence,
            error=error,
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _consume(self, context: ProviderExecutionContext) -> bool:
        marker = self._arm_directory / context.operation_id.value
        try:
            mode = marker.lstat().st_mode
            if not stat.S_ISREG(mode):
                return False
            marker.unlink()
        except FileNotFoundError:
            return False
        return True

    def verify(
        self, context: ProviderExecutionContext, request: VerificationRequest
    ) -> VerificationEvidence:
        return self._delegate.verify(context, request)

    def compensate(
        self, context: ProviderExecutionContext, request: CompensationRequest
    ) -> CompensationEvidence:
        return self._delegate.compensate(context, request)
