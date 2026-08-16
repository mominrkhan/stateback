"""EffectDescriptor and related provider types — `contracts/PROVIDER_ADAPTER_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    CompensationKind,
    EffectOutcome,
    ErrorKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.errors import NormalizedError, parse_optional_error
from stateback.domain.evidence import ProviderEvidence, parse_optional_evidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue, json_to_plain, parse_json_value
from stateback.domain.refs import EffectRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_bool,
    parse_contract_version,
    parse_enum,
    parse_optional_str,
    parse_str,
    parse_str_list,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_KEY_FIELDS = frozenset(
    {
        "scope",
        "replay_window",
        "same_key_same_request_required",
        "conflicting_request_behavior",
        "response_replay_behavior",
    }
)
_DESCRIPTOR_FIELDS = frozenset(
    {
        "contract_version",
        "effect",
        "mutability",
        "risk_level",
        "idempotency_mode",
        "verification_mode",
        "compensation_kind",
        "supports_external_operation_id",
        "immediate_response_can_prove_applied",
        "immediate_response_can_prove_not_applied",
        "provider_key_semantics",
        "documentation",
    }
)
_CONTEXT_FIELDS = frozenset(
    {
        "operation_id",
        "attempt_id",
        "idempotency_identity",
        "provider_idempotency_key",
        "correlation_id",
        "deadline",
    }
)
_REQUEST_FIELDS = frozenset({"effect", "arguments"})
_EXEC_EVIDENCE_FIELDS = frozenset(
    {
        "outcome",
        "evidence",
        "error",
        "external_operation_id",
        "external_resource_ids",
    }
)
_VERIFY_EVIDENCE_FIELDS = frozenset({"outcome", "evidence", "error"})
_COMP_REQ_FIELDS = frozenset(
    {
        "original_operation_id",
        "compensation_id",
        "compensation_attempt_id",
        "original_evidence",
        "compensation_arguments",
        "idempotency_identity",
        "provider_idempotency_key",
    }
)
_COMP_EVIDENCE_FIELDS = frozenset(
    {
        "outcome",
        "evidence",
        "error",
        "external_operation_id",
    }
)
_VALIDATION_RESULT_FIELDS = frozenset({"accepted", "error"})
_VALIDATION_ERROR_KINDS = frozenset(
    {
        ErrorKind.VALIDATION,
        ErrorKind.UNSUPPORTED_CAPABILITY,
        ErrorKind.AUTHENTICATION,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderKeySemantics:
    scope: str
    replay_window: str | None
    same_key_same_request_required: bool
    conflicting_request_behavior: str
    response_replay_behavior: str

    def to_wire(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "replay_window": self.replay_window,
            "same_key_same_request_required": self.same_key_same_request_required,
            "conflicting_request_behavior": self.conflicting_request_behavior,
            "response_replay_behavior": self.response_replay_behavior,
        }

    @classmethod
    def from_wire(cls, raw: object) -> ProviderKeySemantics:
        data = require_mapping(raw, type_name="ProviderKeySemantics")
        reject_unknown_keys(data, _KEY_FIELDS, type_name="ProviderKeySemantics")
        return cls(
            scope=parse_str(
                require_key(data, "scope", type_name="ProviderKeySemantics"),
                field="ProviderKeySemantics.scope",
            ),
            replay_window=parse_optional_str(
                optional_key(data, "replay_window"),
                field="ProviderKeySemantics.replay_window",
            ),
            same_key_same_request_required=parse_bool(
                require_key(
                    data,
                    "same_key_same_request_required",
                    type_name="ProviderKeySemantics",
                ),
                field="ProviderKeySemantics.same_key_same_request_required",
            ),
            conflicting_request_behavior=parse_str(
                require_key(
                    data,
                    "conflicting_request_behavior",
                    type_name="ProviderKeySemantics",
                ),
                field="ProviderKeySemantics.conflicting_request_behavior",
            ),
            response_replay_behavior=parse_str(
                require_key(
                    data, "response_replay_behavior", type_name="ProviderKeySemantics"
                ),
                field="ProviderKeySemantics.response_replay_behavior",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EffectDescriptor:
    contract_version: str
    effect: EffectRef
    mutability: Mutability
    risk_level: RiskLevel
    idempotency_mode: IdempotencyMode
    verification_mode: VerificationMode
    compensation_kind: CompensationKind
    supports_external_operation_id: bool
    immediate_response_can_prove_applied: bool
    immediate_response_can_prove_not_applied: bool
    provider_key_semantics: ProviderKeySemantics | None
    documentation: str

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "EffectDescriptor.contract_version must be v1",
            )
        if self.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
            if self.provider_key_semantics is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "PROVIDER_KEY requires provider_key_semantics",
                )
        elif self.provider_key_semantics is not None:
            raise ContractValidationError(
                "illegal_combination",
                "provider_key_semantics is allowed only for PROVIDER_KEY",
            )
        if (
            self.mutability is Mutability.READ_ONLY
            and self.compensation_kind is not CompensationKind.NONE
        ):
            raise ContractValidationError(
                "illegal_combination",
                "READ_ONLY effects must declare CompensationKind.NONE",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "effect": self.effect.to_wire(),
            "mutability": self.mutability.value,
            "risk_level": self.risk_level.value,
            "idempotency_mode": self.idempotency_mode.value,
            "verification_mode": self.verification_mode.value,
            "compensation_kind": self.compensation_kind.value,
            "supports_external_operation_id": self.supports_external_operation_id,
            "immediate_response_can_prove_applied": (
                self.immediate_response_can_prove_applied
            ),
            "immediate_response_can_prove_not_applied": (
                self.immediate_response_can_prove_not_applied
            ),
            "provider_key_semantics": (
                None
                if self.provider_key_semantics is None
                else self.provider_key_semantics.to_wire()
            ),
            "documentation": self.documentation,
        }

    @classmethod
    def from_wire(cls, raw: object) -> EffectDescriptor:
        data = require_mapping(raw, type_name="EffectDescriptor")
        reject_unknown_keys(data, _DESCRIPTOR_FIELDS, type_name="EffectDescriptor")
        parse_contract_version(
            require_key(data, "contract_version", type_name="EffectDescriptor"),
            type_name="EffectDescriptor",
        )
        key_raw = optional_key(data, "provider_key_semantics")
        return cls(
            contract_version=CONTRACT_VERSION,
            effect=EffectRef.from_wire(
                require_key(data, "effect", type_name="EffectDescriptor")
            ),
            mutability=parse_enum(
                Mutability,
                require_key(data, "mutability", type_name="EffectDescriptor"),
                field="EffectDescriptor.mutability",
            ),
            risk_level=parse_enum(
                RiskLevel,
                require_key(data, "risk_level", type_name="EffectDescriptor"),
                field="EffectDescriptor.risk_level",
            ),
            idempotency_mode=parse_enum(
                IdempotencyMode,
                require_key(data, "idempotency_mode", type_name="EffectDescriptor"),
                field="EffectDescriptor.idempotency_mode",
            ),
            verification_mode=parse_enum(
                VerificationMode,
                require_key(data, "verification_mode", type_name="EffectDescriptor"),
                field="EffectDescriptor.verification_mode",
            ),
            compensation_kind=parse_enum(
                CompensationKind,
                require_key(data, "compensation_kind", type_name="EffectDescriptor"),
                field="EffectDescriptor.compensation_kind",
            ),
            supports_external_operation_id=parse_bool(
                require_key(
                    data,
                    "supports_external_operation_id",
                    type_name="EffectDescriptor",
                ),
                field="EffectDescriptor.supports_external_operation_id",
            ),
            immediate_response_can_prove_applied=parse_bool(
                require_key(
                    data,
                    "immediate_response_can_prove_applied",
                    type_name="EffectDescriptor",
                ),
                field="EffectDescriptor.immediate_response_can_prove_applied",
            ),
            immediate_response_can_prove_not_applied=parse_bool(
                require_key(
                    data,
                    "immediate_response_can_prove_not_applied",
                    type_name="EffectDescriptor",
                ),
                field="EffectDescriptor.immediate_response_can_prove_not_applied",
            ),
            provider_key_semantics=(
                None if key_raw is None else ProviderKeySemantics.from_wire(key_raw)
            ),
            documentation=parse_str(
                require_key(data, "documentation", type_name="EffectDescriptor"),
                field="EffectDescriptor.documentation",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderExecutionContext:
    operation_id: OpaqueId
    attempt_id: OpaqueId
    idempotency_identity: str
    provider_idempotency_key: str | None
    correlation_id: str | None
    deadline: UtcTimestamp | None

    def to_wire(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id.to_wire(),
            "attempt_id": self.attempt_id.to_wire(),
            "idempotency_identity": self.idempotency_identity,
            "provider_idempotency_key": self.provider_idempotency_key,
            "correlation_id": self.correlation_id,
            "deadline": None if self.deadline is None else self.deadline.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> ProviderExecutionContext:
        data = require_mapping(raw, type_name="ProviderExecutionContext")
        reject_unknown_keys(data, _CONTEXT_FIELDS, type_name="ProviderExecutionContext")
        deadline_raw = optional_key(data, "deadline")
        return cls(
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="ProviderExecutionContext"),
                field="ProviderExecutionContext.operation_id",
            ),
            attempt_id=OpaqueId.from_wire(
                require_key(data, "attempt_id", type_name="ProviderExecutionContext"),
                field="ProviderExecutionContext.attempt_id",
            ),
            idempotency_identity=parse_str(
                require_key(
                    data, "idempotency_identity", type_name="ProviderExecutionContext"
                ),
                field="ProviderExecutionContext.idempotency_identity",
            ),
            provider_idempotency_key=parse_optional_str(
                optional_key(data, "provider_idempotency_key"),
                field="ProviderExecutionContext.provider_idempotency_key",
            ),
            correlation_id=parse_optional_str(
                optional_key(data, "correlation_id"),
                field="ProviderExecutionContext.correlation_id",
            ),
            deadline=(
                None
                if deadline_raw is None
                else UtcTimestamp.from_wire(
                    deadline_raw, field="ProviderExecutionContext.deadline"
                )
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderExecutionRequest:
    effect: EffectRef
    arguments: JsonValue

    def to_wire(self) -> dict[str, object]:
        return {
            "effect": self.effect.to_wire(),
            "arguments": json_to_plain(self.arguments),
        }

    @classmethod
    def from_wire(cls, raw: object) -> ProviderExecutionRequest:
        data = require_mapping(raw, type_name="ProviderExecutionRequest")
        reject_unknown_keys(data, _REQUEST_FIELDS, type_name="ProviderExecutionRequest")
        return cls(
            effect=EffectRef.from_wire(
                require_key(data, "effect", type_name="ProviderExecutionRequest")
            ),
            arguments=parse_json_value(
                require_key(data, "arguments", type_name="ProviderExecutionRequest"),
                field="ProviderExecutionRequest.arguments",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionEvidence:
    outcome: EffectOutcome
    evidence: ProviderEvidence | None
    error: NormalizedError | None
    external_operation_id: str | None
    external_resource_ids: tuple[str, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "evidence": None if self.evidence is None else self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
            "external_operation_id": self.external_operation_id,
            "external_resource_ids": list(self.external_resource_ids),
        }

    @classmethod
    def from_wire(cls, raw: object) -> ExecutionEvidence:
        data = require_mapping(raw, type_name="ExecutionEvidence")
        reject_unknown_keys(data, _EXEC_EVIDENCE_FIELDS, type_name="ExecutionEvidence")
        return cls(
            outcome=parse_enum(
                EffectOutcome,
                require_key(data, "outcome", type_name="ExecutionEvidence"),
                field="ExecutionEvidence.outcome",
            ),
            evidence=parse_optional_evidence(optional_key(data, "evidence")),
            error=parse_optional_error(optional_key(data, "error")),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="ExecutionEvidence.external_operation_id",
            ),
            external_resource_ids=parse_str_list(
                require_key(
                    data, "external_resource_ids", type_name="ExecutionEvidence"
                ),
                field="ExecutionEvidence.external_resource_ids",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationEvidence:
    outcome: EffectOutcome
    evidence: ProviderEvidence
    error: NormalizedError | None

    def to_wire(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "evidence": self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> VerificationEvidence:
        data = require_mapping(raw, type_name="VerificationEvidence")
        reject_unknown_keys(
            data, _VERIFY_EVIDENCE_FIELDS, type_name="VerificationEvidence"
        )
        return cls(
            outcome=parse_enum(
                EffectOutcome,
                require_key(data, "outcome", type_name="VerificationEvidence"),
                field="VerificationEvidence.outcome",
            ),
            evidence=ProviderEvidence.from_wire(
                require_key(data, "evidence", type_name="VerificationEvidence")
            ),
            error=parse_optional_error(optional_key(data, "error")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationRequest:
    original_operation_id: OpaqueId
    compensation_id: OpaqueId
    compensation_attempt_id: OpaqueId
    original_evidence: tuple[ProviderEvidence, ...]
    compensation_arguments: JsonValue
    idempotency_identity: str
    provider_idempotency_key: str | None

    def to_wire(self) -> dict[str, object]:
        return {
            "original_operation_id": self.original_operation_id.to_wire(),
            "compensation_id": self.compensation_id.to_wire(),
            "compensation_attempt_id": self.compensation_attempt_id.to_wire(),
            "original_evidence": [item.to_wire() for item in self.original_evidence],
            "compensation_arguments": json_to_plain(self.compensation_arguments),
            "idempotency_identity": self.idempotency_identity,
            "provider_idempotency_key": self.provider_idempotency_key,
        }

    @classmethod
    def from_wire(cls, raw: object) -> CompensationRequest:
        data = require_mapping(raw, type_name="CompensationRequest")
        reject_unknown_keys(data, _COMP_REQ_FIELDS, type_name="CompensationRequest")
        evidence_raw = require_key(
            data, "original_evidence", type_name="CompensationRequest"
        )
        if not isinstance(evidence_raw, list):
            raise ContractValidationError(
                "invalid_type",
                "CompensationRequest.original_evidence must be an array",
            )
        return cls(
            original_operation_id=OpaqueId.from_wire(
                require_key(
                    data, "original_operation_id", type_name="CompensationRequest"
                ),
                field="CompensationRequest.original_operation_id",
            ),
            compensation_id=OpaqueId.from_wire(
                require_key(data, "compensation_id", type_name="CompensationRequest"),
                field="CompensationRequest.compensation_id",
            ),
            compensation_attempt_id=OpaqueId.from_wire(
                require_key(
                    data, "compensation_attempt_id", type_name="CompensationRequest"
                ),
                field="CompensationRequest.compensation_attempt_id",
            ),
            original_evidence=tuple(
                ProviderEvidence.from_wire(item) for item in evidence_raw
            ),
            compensation_arguments=parse_json_value(
                require_key(
                    data, "compensation_arguments", type_name="CompensationRequest"
                ),
                field="CompensationRequest.compensation_arguments",
            ),
            idempotency_identity=parse_str(
                require_key(
                    data, "idempotency_identity", type_name="CompensationRequest"
                ),
                field="CompensationRequest.idempotency_identity",
            ),
            provider_idempotency_key=parse_optional_str(
                optional_key(data, "provider_idempotency_key"),
                field="CompensationRequest.provider_idempotency_key",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationEvidence:
    outcome: EffectOutcome
    evidence: ProviderEvidence | None
    error: NormalizedError | None
    external_operation_id: str | None

    def to_wire(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "evidence": None if self.evidence is None else self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
            "external_operation_id": self.external_operation_id,
        }

    @classmethod
    def from_wire(cls, raw: object) -> CompensationEvidence:
        data = require_mapping(raw, type_name="CompensationEvidence")
        reject_unknown_keys(
            data, _COMP_EVIDENCE_FIELDS, type_name="CompensationEvidence"
        )
        return cls(
            outcome=parse_enum(
                EffectOutcome,
                require_key(data, "outcome", type_name="CompensationEvidence"),
                field="CompensationEvidence.outcome",
            ),
            evidence=parse_optional_evidence(optional_key(data, "evidence")),
            error=parse_optional_error(optional_key(data, "error")),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="CompensationEvidence.external_operation_id",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationResult:
    accepted: bool
    error: NormalizedError | None

    def __post_init__(self) -> None:
        if self.accepted and self.error is not None:
            raise ContractValidationError(
                "illegal_combination",
                "accepted ValidationResult must not include an error",
            )
        if not self.accepted and self.error is None:
            raise ContractValidationError(
                "illegal_combination",
                "rejected ValidationResult requires an error",
            )
        if self.error is not None and self.error.kind not in _VALIDATION_ERROR_KINDS:
            raise ContractValidationError(
                "illegal_combination",
                "ValidationResult.error.kind must be VALIDATION, "
                "UNSUPPORTED_CAPABILITY, or AUTHENTICATION",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "error": None if self.error is None else self.error.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> ValidationResult:
        data = require_mapping(raw, type_name="ValidationResult")
        reject_unknown_keys(
            data, _VALIDATION_RESULT_FIELDS, type_name="ValidationResult"
        )
        return cls(
            accepted=parse_bool(
                require_key(data, "accepted", type_name="ValidationResult"),
                field="ValidationResult.accepted",
            ),
            error=parse_optional_error(optional_key(data, "error")),
        )
