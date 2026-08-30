"""Deterministic in-process reference provider adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace

from stateback.domain.canonical import sha256_hex
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
    CompensationKind,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    IdempotencyMode,
    VerificationMode,
    VerificationTarget,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonObject, JsonValue, json_from_plain
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.normalize import evidence_for_unclassified_exception
from stateback.providers.reference.clock import Clock
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_EVENTUAL,
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_READ_RESOURCE,
    REFERENCE_DESCRIPTORS,
    REFERENCE_EFFECTS,
    REFERENCE_PROVIDER,
)
from stateback.providers.reference.scripts import (
    ReferenceCompensateScript,
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.providers.reference.store import ReferenceResource, ReferenceStore

_EMPTY = json_from_plain({})


@dataclass(frozen=True, slots=True, kw_only=True)
class _ExecuteSpec:
    mutates: bool
    outcome: EffectOutcome
    status: str
    kind: ErrorKind | None = None
    code: str | None = None
    retryable: bool = False
    http: int | None = None
    return_ids: bool = False
    message: str | None = None


_EXECUTE_SPECS: dict[ReferenceExecuteScript, _ExecuteSpec] = {
    ReferenceExecuteScript.APPLIED: _ExecuteSpec(
        mutates=True,
        outcome=EffectOutcome.APPLIED,
        status="applied",
        return_ids=True,
    ),
    ReferenceExecuteScript.NOT_APPLIED_VALIDATION: _ExecuteSpec(
        mutates=False,
        outcome=EffectOutcome.NOT_APPLIED,
        status="rejected",
        kind=ErrorKind.VALIDATION,
        code="ref.validation.missing_resource_id",
    ),
    ReferenceExecuteScript.NOT_APPLIED_REJECTED: _ExecuteSpec(
        mutates=False,
        outcome=EffectOutcome.NOT_APPLIED,
        status="rejected",
        kind=ErrorKind.PROVIDER_REJECTED,
        code="ref.rejected.before_accept",
        http=400,
        message="provider rejected request before acceptance",
    ),
    ReferenceExecuteScript.NOT_APPLIED_UNAVAILABLE: _ExecuteSpec(
        mutates=False,
        outcome=EffectOutcome.NOT_APPLIED,
        status="unavailable",
        kind=ErrorKind.PROVIDER_UNAVAILABLE,
        code="ref.unavailable.no_accept",
        retryable=True,
        http=503,
    ),
    ReferenceExecuteScript.NOT_APPLIED_RATE_LIMIT: _ExecuteSpec(
        mutates=False,
        outcome=EffectOutcome.NOT_APPLIED,
        status="rate_limited",
        kind=ErrorKind.RATE_LIMITED,
        code="ref.rate_limited.not_accepted",
        retryable=True,
        http=429,
    ),
    ReferenceExecuteScript.NOT_APPLIED_AUTH: _ExecuteSpec(
        mutates=False,
        outcome=EffectOutcome.NOT_APPLIED,
        status="auth",
        kind=ErrorKind.AUTHENTICATION,
        code="ref.auth.missing",
        http=401,
        message="provider authentication failed",
    ),
    ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND: _ExecuteSpec(
        mutates=True,
        outcome=EffectOutcome.UNKNOWN,
        status="timeout",
        kind=ErrorKind.TRANSIENT_TRANSPORT,
        code="ref.timeout.after_send",
        retryable=True,
    ),
    ReferenceExecuteScript.UNKNOWN_MALFORMED: _ExecuteSpec(
        mutates=True,
        outcome=EffectOutcome.UNKNOWN,
        status="malformed",
        kind=ErrorKind.MALFORMED_PROVIDER_RESPONSE,
        code="ref.malformed.after_accept",
        http=200,
    ),
    ReferenceExecuteScript.UNKNOWN_RATE_LIMIT_AMBIGUOUS: _ExecuteSpec(
        mutates=True,
        outcome=EffectOutcome.UNKNOWN,
        status="rate_limited",
        kind=ErrorKind.RATE_LIMITED,
        code="ref.rate_limited.ambiguous",
        retryable=True,
        http=429,
    ),
    ReferenceExecuteScript.APPLIED_RESPONSE_LOST: _ExecuteSpec(
        mutates=True,
        outcome=EffectOutcome.UNKNOWN,
        status="timeout",
        kind=ErrorKind.TRANSIENT_TRANSPORT,
        code="ref.timeout.after_send",
        retryable=True,
    ),
}


def _fingerprint(resource_id: str) -> str:
    return sha256_hex(json_from_plain({"resource_id": resource_id}))


def _resource_id_of(arguments: JsonValue) -> str | None:
    if not isinstance(arguments, JsonObject):
        return None
    value = arguments.as_dict().get("resource_id")
    if not isinstance(value, str):
        return None
    return value


def _norm_error(
    *,
    kind: ErrorKind,
    code: str,
    retryable: bool = False,
    http: int | None = None,
    message: str | None = None,
) -> NormalizedError:
    return NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=kind,
        code=code,
        message=code if message is None else message,
        retryable_infrastructure=retryable,
        provider_http_status=http,
        provider_error_code=None,
        retry_after_seconds=None,
        details=_EMPTY,
    )


def _verification_source(mode: VerificationMode) -> EvidenceSource:
    if mode is VerificationMode.OPERATION_LOOKUP:
        return EvidenceSource.OPERATION_LOOKUP
    if mode is VerificationMode.READ_BACK:
        return EvidenceSource.READ_BACK
    return EvidenceSource.CUSTOM


class ReferenceAdapter:
    def __init__(
        self,
        *,
        store: ReferenceStore,
        clock: Clock,
        visibility_delay_seconds: int = 0,
    ) -> None:
        if visibility_delay_seconds < 0:
            raise ContractValidationError(
                "invalid_range",
                "visibility_delay_seconds must be >= 0",
            )
        self._store = store
        self._clock = clock
        self._visibility_delay_seconds = visibility_delay_seconds
        self._execute_scripts: list[ReferenceExecuteScript] = []
        self._verify_scripts: list[ReferenceVerifyScript] = []
        self._compensate_scripts: list[ReferenceCompensateScript] = []
        self._compensation_keys: dict[str, str] = {}

    def enqueue_execute(self, script: ReferenceExecuteScript) -> None:
        self._execute_scripts.append(script)

    def enqueue_verify(self, script: ReferenceVerifyScript) -> None:
        self._verify_scripts.append(script)

    def enqueue_compensate(self, script: ReferenceCompensateScript) -> None:
        self._compensate_scripts.append(script)

    def supported_effects(self) -> tuple[EffectRef, ...]:
        return REFERENCE_EFFECTS

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        desc = REFERENCE_DESCRIPTORS.get(effect)
        if desc is None:
            raise UnsupportedEffectError(effect)
        return desc

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        if request.effect not in REFERENCE_EFFECTS:
            return ValidationResult(
                accepted=False,
                error=_norm_error(
                    kind=ErrorKind.UNSUPPORTED_CAPABILITY,
                    code="ref.validation.unknown_effect",
                ),
            )
        if not isinstance(request.arguments, JsonObject):
            return ValidationResult(
                accepted=False,
                error=_norm_error(
                    kind=ErrorKind.VALIDATION,
                    code="ref.validation.arguments_not_object",
                ),
            )
        mapping = request.arguments.as_dict()
        if "resource_id" not in mapping:
            return ValidationResult(
                accepted=False,
                error=_norm_error(
                    kind=ErrorKind.VALIDATION,
                    code="ref.validation.missing_resource_id",
                ),
            )
        resource_id = mapping["resource_id"]
        if not isinstance(resource_id, str) or resource_id == "":
            return ValidationResult(
                accepted=False,
                error=_norm_error(
                    kind=ErrorKind.VALIDATION,
                    code="ref.validation.empty_resource_id",
                ),
            )
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
        if request.effect not in REFERENCE_EFFECTS:
            raise UnsupportedEffectError(request.effect)
        try:
            return self._execute_body(context, request)
        except (UnsupportedEffectError, ContractValidationError):
            raise
        except Exception as exc:
            outcome, error, evidence = evidence_for_unclassified_exception(
                exc=exc,
                observed_at=self._clock.now(),
                provider=REFERENCE_PROVIDER,
            )
            return ExecutionEvidence(
                outcome=outcome,
                evidence=evidence,
                error=error,
                external_operation_id=None,
                external_resource_ids=(),
            )

    def verify(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence:
        if request.effect not in REFERENCE_EFFECTS:
            raise UnsupportedEffectError(request.effect)
        try:
            return self._verify_body(context, request)
        except (UnsupportedEffectError, ContractValidationError):
            raise
        except Exception as exc:
            desc = REFERENCE_DESCRIPTORS[request.effect]
            outcome, error, evidence = evidence_for_unclassified_exception(
                exc=exc,
                observed_at=self._clock.now(),
                provider=REFERENCE_PROVIDER,
            )
            evidence = replace(
                evidence, source=_verification_source(desc.verification_mode)
            )
            return VerificationEvidence(outcome=outcome, evidence=evidence, error=error)

    def compensate(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence:
        try:
            return self._compensate_body(context, request)
        except (UnsupportedEffectError, ContractValidationError):
            raise
        except Exception as exc:
            outcome, error, evidence = evidence_for_unclassified_exception(
                exc=exc,
                observed_at=self._clock.now(),
                provider=REFERENCE_PROVIDER,
            )
            return CompensationEvidence(
                outcome=outcome,
                evidence=evidence,
                error=error,
                external_operation_id=None,
            )

    def _execute_body(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence:
        desc = self.descriptor(request.effect)
        validation = self.validate_execution(request)
        if not validation.accepted:
            return self._execution_from_error(
                context,
                outcome=EffectOutcome.NOT_APPLIED,
                error=validation.error,
                status="rejected",
                sent=False,
            )
        resource_id = _resource_id_of(request.arguments)
        if resource_id is None:
            raise ContractValidationError(
                "illegal_combination",
                "validated execute request must include resource_id",
            )
        if context.deadline is not None and self._clock.now() >= context.deadline:
            return self._execution_from_error(
                context,
                outcome=EffectOutcome.NOT_APPLIED,
                error=_norm_error(
                    kind=ErrorKind.TRANSIENT_TRANSPORT,
                    code="ref.deadline.not_sent",
                    retryable=True,
                ),
                status="rejected",
                sent=False,
            )
        if (
            desc.idempotency_mode is IdempotencyMode.PROVIDER_KEY
            and context.provider_idempotency_key is None
        ):
            return self._execution_from_error(
                context,
                outcome=EffectOutcome.NOT_APPLIED,
                error=_norm_error(
                    kind=ErrorKind.VALIDATION,
                    code="ref.validation.provider_key_required",
                ),
                status="rejected",
                sent=False,
            )
        fingerprint = _fingerprint(resource_id)
        if (
            desc.idempotency_mode is IdempotencyMode.PROVIDER_KEY
            and context.provider_idempotency_key is not None
        ):
            existing = self._store.get_by_provider_key(context.provider_idempotency_key)
            if existing is not None:
                if existing.arguments_fingerprint == fingerprint:
                    return self._applied_from_row(existing)
                return self._execution_from_error(
                    context,
                    outcome=EffectOutcome.NOT_APPLIED,
                    error=_norm_error(
                        kind=ErrorKind.PROVIDER_REJECTED,
                        code="ref.duplicate.conflict",
                        http=409,
                    ),
                    status="rejected",
                    sent=False,
                )
        if request.effect in (EFFECT_MUTATE_NATURAL, EFFECT_READ_RESOURCE):
            existing = self._store.get_by_resource_id(resource_id)
            if existing is not None and existing.applied:
                if request.effect is EFFECT_READ_RESOURCE:
                    return self._read_success(context, resource_id)
                return self._applied_from_row(existing)
        script = (
            self._execute_scripts.pop(0)
            if self._execute_scripts
            else ReferenceExecuteScript.APPLIED
        )
        spec = _EXECUTE_SPECS[script]
        if request.effect is EFFECT_READ_RESOURCE:
            return self._execute_read(context, resource_id, spec)
        if spec.mutates:
            row = self._put_mutation(
                context=context,
                effect=request.effect,
                resource_id=resource_id,
                fingerprint=fingerprint,
            )
            return self._execution_from_spec(
                context,
                spec=spec,
                resource_id=resource_id,
                stored=row,
            )
        return self._execution_from_spec(
            context,
            spec=spec,
            resource_id=resource_id,
            stored=None,
        )

    def _execute_read(
        self,
        context: ProviderExecutionContext,
        resource_id: str,
        spec: _ExecuteSpec,
    ) -> ExecutionEvidence:
        if spec.outcome is EffectOutcome.UNKNOWN:
            error = _norm_error(
                kind=spec.kind or ErrorKind.INTERNAL,
                code=spec.code or "ref.internal.unclassified",
                retryable=spec.retryable,
                http=spec.http,
                message=spec.message,
            )
            return self._execution_from_error(
                context,
                outcome=EffectOutcome.UNKNOWN,
                error=error,
                status=spec.status,
                sent=True,
            )
        if spec.kind is not None:
            error = _norm_error(
                kind=spec.kind,
                code=spec.code or "ref.validation.missing_resource_id",
                retryable=spec.retryable,
                http=spec.http,
                message=spec.message,
            )
            return self._execution_from_error(
                context,
                outcome=EffectOutcome.NOT_APPLIED,
                error=error,
                status=spec.status,
                sent=False,
            )
        return self._read_success(context, resource_id)

    def _read_success(
        self, context: ProviderExecutionContext, resource_id: str
    ) -> ExecutionEvidence:
        present = self._store.get_by_resource_id(resource_id) is not None
        return ExecutionEvidence(
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=self._exec_evidence(
                status="read",
                request_id=f"refreq:{context.attempt_id.value}",
                external_operation_id=None,
                external_resource_ids=(),
                fields=json_from_plain(
                    {
                        "present": "true" if present else "false",
                        "resource_id": resource_id,
                    }
                ),
            ),
            error=None,
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _put_mutation(
        self,
        *,
        context: ProviderExecutionContext,
        effect: EffectRef,
        resource_id: str,
        fingerprint: str,
    ) -> ReferenceResource:
        store_id = resource_id
        if (
            effect is EFFECT_MUTATE_NONE
            and self._store.get_by_resource_id(resource_id) is not None
        ):
            store_id = resource_id + "#" + context.attempt_id.value
        row = ReferenceResource(
            resource_id=store_id,
            action=effect.action,
            external_operation_id=(
                f"refop:{context.operation_id.value}:{context.attempt_id.value}"
            ),
            provider_idempotency_key=context.provider_idempotency_key,
            arguments_fingerprint=fingerprint,
            applied=True,
            compensated=False,
            mitigated=False,
            created_at=self._clock.now(),
        )
        self._store.put(row)
        return row

    def _applied_from_row(self, row: ReferenceResource) -> ExecutionEvidence:
        attempt = row.external_operation_id.rsplit(":", 1)[-1]
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._exec_evidence(
                status="applied",
                request_id=f"refreq:{attempt}",
                external_operation_id=row.external_operation_id,
                external_resource_ids=(row.resource_id,),
                fields=json_from_plain(
                    {"mutation": "create", "resource_id": row.resource_id}
                ),
            ),
            error=None,
            external_operation_id=row.external_operation_id,
            external_resource_ids=(row.resource_id,),
        )

    def _execution_from_spec(
        self,
        context: ProviderExecutionContext,
        *,
        spec: _ExecuteSpec,
        resource_id: str,
        stored: ReferenceResource | None,
    ) -> ExecutionEvidence:
        error = None
        if spec.kind is not None and spec.code is not None:
            error = _norm_error(
                kind=spec.kind,
                code=spec.code,
                retryable=spec.retryable,
                http=spec.http,
                message=spec.message,
            )
        ids = (resource_id,) if spec.return_ids else ()
        op_id = stored.external_operation_id if spec.return_ids and stored else None
        request_id = f"refreq:{context.attempt_id.value}" if spec.mutates else None
        fields = _EMPTY
        if spec.outcome is EffectOutcome.APPLIED:
            fields = json_from_plain({"mutation": "create", "resource_id": resource_id})
        return ExecutionEvidence(
            outcome=spec.outcome,
            evidence=self._exec_evidence(
                status=spec.status,
                request_id=request_id,
                external_operation_id=op_id,
                external_resource_ids=ids,
                fields=fields,
            ),
            error=error,
            external_operation_id=op_id,
            external_resource_ids=ids,
        )

    def _execution_from_error(
        self,
        context: ProviderExecutionContext,
        *,
        outcome: EffectOutcome,
        error: NormalizedError | None,
        status: str,
        sent: bool,
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=outcome,
            evidence=self._exec_evidence(
                status=status,
                request_id=f"refreq:{context.attempt_id.value}" if sent else None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
            ),
            error=error,
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _verify_body(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence:
        desc = self.descriptor(request.effect)
        if desc.verification_mode is VerificationMode.NONE:
            return self._unsupported_verification()
        script = (
            self._verify_scripts.pop(0)
            if self._verify_scripts
            else ReferenceVerifyScript.STORE
        )
        source = _verification_source(desc.verification_mode)
        if script is not ReferenceVerifyScript.STORE:
            return self._forced_verification(script, source)
        row = self._lookup_verify_row(context, request)
        if request.target is VerificationTarget.COMPENSATION:
            return self._verify_compensation_target(request.effect, row, source)
        return self._verify_original_target(request.effect, row, source)

    def _lookup_verify_row(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> ReferenceResource | None:
        if request.external_operation_id is not None:
            found = self._store.get_by_external_operation_id(
                request.external_operation_id
            )
            if found is not None:
                return found
        if request.external_resource_ids:
            found = self._store.get_by_resource_id(request.external_resource_ids[0])
            if found is not None:
                return found
        if context.provider_idempotency_key is not None:
            found = self._store.get_by_provider_key(context.provider_idempotency_key)
            if found is not None:
                return found
        return None

    def _verify_compensation_target(
        self,
        effect: EffectRef,
        row: ReferenceResource | None,
        source: EvidenceSource,
    ) -> VerificationEvidence:
        if row is not None and (row.compensated or row.mitigated):
            return self._verify_outcome(EffectOutcome.APPLIED, source, row=row)
        if row is not None:
            return self._verify_outcome(EffectOutcome.NOT_APPLIED, source, row=row)
        if effect is EFFECT_MUTATE_EVENTUAL:
            return self._verify_visibility_unknown(source)
        return self._verify_outcome(EffectOutcome.NOT_APPLIED, source, row=None)

    def _verify_original_target(
        self,
        effect: EffectRef,
        row: ReferenceResource | None,
        source: EvidenceSource,
    ) -> VerificationEvidence:
        if row is not None and row.applied:
            if effect is EFFECT_MUTATE_EVENTUAL:
                age = (self._clock.now().value - row.created_at.value).total_seconds()
                if age < self._visibility_delay_seconds:
                    return self._verify_visibility_unknown(source)
            return self._verify_outcome(EffectOutcome.APPLIED, source, row=row)
        if effect is EFFECT_MUTATE_EVENTUAL:
            return self._verify_visibility_unknown(source)
        return self._verify_outcome(EffectOutcome.NOT_APPLIED, source, row=None)

    def _forced_verification(
        self, script: ReferenceVerifyScript, source: EvidenceSource
    ) -> VerificationEvidence:
        if script is ReferenceVerifyScript.APPLIED:
            return VerificationEvidence(
                outcome=EffectOutcome.APPLIED,
                evidence=self._verify_evidence(
                    source=source,
                    status="applied",
                    fields=json_from_plain({"forced": "true"}),
                ),
                error=None,
            )
        if script is ReferenceVerifyScript.NOT_APPLIED:
            return self._verify_outcome(EffectOutcome.NOT_APPLIED, source, row=None)
        mapping: dict[ReferenceVerifyScript, tuple[ErrorKind, str]] = {
            ReferenceVerifyScript.UNKNOWN_TRANSPORT: (
                ErrorKind.TRANSIENT_TRANSPORT,
                "ref.verify.transport",
            ),
            ReferenceVerifyScript.UNKNOWN_INCONCLUSIVE: (
                ErrorKind.PROVIDER_INCONSISTENT,
                "ref.verify.inconclusive",
            ),
            ReferenceVerifyScript.UNKNOWN_MALFORMED: (
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "ref.verify.malformed",
            ),
            ReferenceVerifyScript.UNKNOWN_INCONSISTENT: (
                ErrorKind.PROVIDER_INCONSISTENT,
                "ref.verify.inconsistent",
            ),
        }
        kind, code = mapping[script]
        retryable = kind is ErrorKind.TRANSIENT_TRANSPORT
        return VerificationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._verify_evidence(source=source, status="timeout"),
            error=_norm_error(kind=kind, code=code, retryable=retryable),
        )

    def _verify_visibility_unknown(
        self, source: EvidenceSource
    ) -> VerificationEvidence:
        return VerificationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._verify_evidence(source=source, status="timeout"),
            error=_norm_error(
                kind=ErrorKind.TRANSIENT_TRANSPORT,
                code="ref.verify.visibility_window",
                retryable=True,
            ),
        )

    def _verify_outcome(
        self,
        outcome: EffectOutcome,
        source: EvidenceSource,
        *,
        row: ReferenceResource | None,
    ) -> VerificationEvidence:
        status = "applied" if outcome is EffectOutcome.APPLIED else "not_found"
        ids = (
            (row.resource_id,)
            if row is not None and outcome is EffectOutcome.APPLIED
            else ()
        )
        op_id = (
            row.external_operation_id
            if row is not None and outcome is EffectOutcome.APPLIED
            else None
        )
        return VerificationEvidence(
            outcome=outcome,
            evidence=self._verify_evidence(
                source=source,
                status=status,
                external_operation_id=op_id,
                external_resource_ids=ids,
            ),
            error=None,
        )

    def _unsupported_verification(self) -> VerificationEvidence:
        return VerificationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._verify_evidence(
                source=EvidenceSource.CUSTOM, status="unsupported"
            ),
            error=_norm_error(
                kind=ErrorKind.UNSUPPORTED_CAPABILITY,
                code="ref.unsupported.verification",
                message="verification is not declared for this effect",
            ),
        )

    def _compensate_body(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence:
        del context
        arguments_error = self._compensation_arguments_error(
            request.compensation_arguments
        )
        if arguments_error is not None:
            return self._compensation_not_applied(arguments_error)
        resource_id = _resource_id_of(request.compensation_arguments)
        if resource_id is None:
            raise ContractValidationError(
                "illegal_combination",
                "validated compensate request must include resource_id",
            )
        if request.provider_idempotency_key is not None:
            replay = self._compensation_replay(request.provider_idempotency_key)
            if replay is not None:
                return replay
        row = self._lookup_compensation_row(request, resource_id)
        if row is None:
            return self._compensation_not_applied(
                _norm_error(
                    kind=ErrorKind.PROVIDER_REJECTED,
                    code="ref.rejected.before_accept",
                    http=400,
                    message="provider rejected request before acceptance",
                )
            )
        desc = self._descriptor_for_action(row.action)
        if desc is None:
            raise UnsupportedEffectError(
                EffectRef(provider=REFERENCE_PROVIDER, action=row.action, version="v1")
            )
        if desc.compensation_kind is CompensationKind.NONE or desc.effect in (
            EFFECT_MUTATE_NONE,
            EFFECT_READ_RESOURCE,
        ):
            return self._unsupported_compensation()
        script = (
            self._compensate_scripts.pop(0)
            if self._compensate_scripts
            else ReferenceCompensateScript.APPLIED
        )
        if script is ReferenceCompensateScript.NOT_APPLIED_REJECTED:
            return self._compensation_not_applied(
                _norm_error(
                    kind=ErrorKind.PROVIDER_REJECTED,
                    code="ref.rejected.before_accept",
                    http=400,
                    message="provider rejected request before acceptance",
                )
            )
        marked = self._mark_compensated(row, desc.compensation_kind)
        if request.provider_idempotency_key is not None:
            self._compensation_keys[request.provider_idempotency_key] = (
                marked.resource_id
            )
        cop_id = (
            f"refcop:{request.compensation_id.value}:"
            f"{request.compensation_attempt_id.value}"
        )
        if script is ReferenceCompensateScript.APPLIED:
            return CompensationEvidence(
                outcome=EffectOutcome.APPLIED,
                evidence=self._exec_evidence(
                    status="applied",
                    request_id=f"refreq:{request.compensation_attempt_id.value}",
                    external_operation_id=cop_id,
                    external_resource_ids=(marked.resource_id,),
                    fields=_EMPTY,
                ),
                error=None,
                external_operation_id=cop_id,
            )
        kind = (
            ErrorKind.TRANSIENT_TRANSPORT
            if script is ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND
            else ErrorKind.MALFORMED_PROVIDER_RESPONSE
        )
        code = (
            "ref.timeout.after_send"
            if script is ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND
            else "ref.malformed.after_accept"
        )
        http = None if kind is ErrorKind.TRANSIENT_TRANSPORT else 200
        return CompensationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._exec_evidence(
                status="timeout"
                if kind is ErrorKind.TRANSIENT_TRANSPORT
                else "malformed",
                request_id=f"refreq:{request.compensation_attempt_id.value}",
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
            ),
            error=_norm_error(
                kind=kind,
                code=code,
                retryable=kind is ErrorKind.TRANSIENT_TRANSPORT,
                http=http,
            ),
            external_operation_id=None,
        )

    def _compensation_replay(self, key: str) -> CompensationEvidence | None:
        row = self._store.get_by_provider_key(key)
        if row is None:
            stored_id = self._compensation_keys.get(key)
            if stored_id is not None:
                row = self._store.get_by_resource_id(stored_id)
        if row is None or not (row.compensated or row.mitigated):
            return None
        return CompensationEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._exec_evidence(
                status="applied",
                request_id=None,
                external_operation_id=row.external_operation_id,
                external_resource_ids=(row.resource_id,),
                fields=_EMPTY,
            ),
            error=None,
            external_operation_id=row.external_operation_id,
        )

    def _lookup_compensation_row(
        self, request: CompensationRequest, resource_id: str
    ) -> ReferenceResource | None:
        for evidence in request.original_evidence:
            if evidence.external_resource_ids:
                found = self._store.get_by_resource_id(
                    evidence.external_resource_ids[0]
                )
                if found is not None:
                    return found
            if evidence.external_operation_id is not None:
                found = self._store.get_by_external_operation_id(
                    evidence.external_operation_id
                )
                if found is not None:
                    return found
        if request.provider_idempotency_key is not None:
            found = self._store.get_by_provider_key(request.provider_idempotency_key)
            if found is not None:
                return found
        return self._store.get_by_resource_id(resource_id)

    def _mark_compensated(
        self, row: ReferenceResource, kind: CompensationKind
    ) -> ReferenceResource:
        if kind is CompensationKind.MITIGATING:
            updated = replace(row, mitigated=True)
        else:
            updated = replace(row, compensated=True)
        self._store.replace(updated)
        return updated

    def _descriptor_for_action(self, action: str) -> EffectDescriptor | None:
        for effect, desc in REFERENCE_DESCRIPTORS.items():
            if effect.action == action:
                return desc
        return None

    def _compensation_arguments_error(
        self, arguments: JsonValue
    ) -> NormalizedError | None:
        if not isinstance(arguments, JsonObject):
            return _norm_error(
                kind=ErrorKind.VALIDATION,
                code="ref.validation.arguments_not_object",
            )
        mapping = arguments.as_dict()
        if "resource_id" not in mapping:
            return _norm_error(
                kind=ErrorKind.VALIDATION,
                code="ref.validation.missing_resource_id",
            )
        resource_id = mapping["resource_id"]
        if not isinstance(resource_id, str) or resource_id == "":
            return _norm_error(
                kind=ErrorKind.VALIDATION,
                code="ref.validation.empty_resource_id",
            )
        return None

    def _compensation_not_applied(self, error: NormalizedError) -> CompensationEvidence:
        if error.kind is ErrorKind.UNSUPPORTED_CAPABILITY:
            return self._unsupported_compensation()
        return CompensationEvidence(
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=self._exec_evidence(
                status="rejected",
                request_id=None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
            ),
            error=error,
            external_operation_id=None,
        )

    def _unsupported_compensation(self) -> CompensationEvidence:
        return CompensationEvidence(
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=None,
            error=_norm_error(
                kind=ErrorKind.UNSUPPORTED_CAPABILITY,
                code="ref.unsupported.compensation",
                message="compensation is not declared for this effect",
            ),
            external_operation_id=None,
        )

    def _exec_evidence(
        self,
        *,
        status: str,
        request_id: str | None,
        external_operation_id: str | None,
        external_resource_ids: tuple[str, ...],
        fields: JsonValue,
    ) -> ProviderEvidence:
        return ProviderEvidence(
            source=EvidenceSource.EXECUTION_RESPONSE,
            provider=REFERENCE_PROVIDER,
            observed_at=self._clock.now(),
            provider_status=status,
            provider_request_id=request_id,
            external_operation_id=external_operation_id,
            external_resource_ids=external_resource_ids,
            evidence_fields=fields,
            raw_reference=None,
        )

    def _verify_evidence(
        self,
        *,
        source: EvidenceSource,
        status: str,
        external_operation_id: str | None = None,
        external_resource_ids: tuple[str, ...] = (),
        fields: JsonValue | None = None,
    ) -> ProviderEvidence:
        return ProviderEvidence(
            source=source,
            provider=REFERENCE_PROVIDER,
            observed_at=self._clock.now(),
            provider_status=status,
            provider_request_id=None,
            external_operation_id=external_operation_id,
            external_resource_ids=external_resource_ids,
            evidence_fields=_EMPTY if fields is None else fields,
            raw_reference=None,
        )
