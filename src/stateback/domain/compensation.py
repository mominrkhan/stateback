"""Compensation records — `contracts/COMPENSATION_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    INITIAL_COMPENSATION_VERSION,
    ArgumentsMode,
    AttemptState,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    OperationState,
)
from stateback.domain.errors import NormalizedError, parse_optional_error
from stateback.domain.evidence import ProviderEvidence, parse_optional_evidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId, parse_optional_opaque_id
from stateback.domain.intent import compensation_idempotency_identity
from stateback.domain.jsonutil import (
    JsonValue,
    json_to_plain,
    parse_optional_json_value,
)
from stateback.domain.refs import PrincipalRef
from stateback.domain.secrets import reject_secrets_in_json
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_optional_enum,
    parse_optional_str,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_COMP_FIELDS = frozenset(
    {
        "contract_version",
        "compensation_id",
        "original_operation_id",
        "kind",
        "state",
        "version",
        "intent_digest",
        "arguments_mode",
        "arguments",
        "arguments_ref",
        "idempotency_identity",
        "requested_by",
        "policy_decision_id",
        "created_at",
        "updated_at",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "contract_version",
        "compensation_attempt_id",
        "compensation_id",
        "attempt_number",
        "state",
        "started_at",
        "completed_at",
        "provider_idempotency_key",
        "external_operation_id",
        "outcome",
        "evidence",
        "error",
    }
)

PARENT_FOR_COMPENSATION_STATE: dict[CompensationState, OperationState] = {
    CompensationState.PENDING: OperationState.COMPENSATING,
    CompensationState.EXECUTING: OperationState.COMPENSATING,
    CompensationState.VERIFYING: OperationState.COMPENSATING,
    CompensationState.UNKNOWN: OperationState.COMPENSATION_UNKNOWN,
    CompensationState.SUCCEEDED: OperationState.COMPENSATED,
    CompensationState.FAILED: OperationState.COMPENSATION_FAILED,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Compensation:
    contract_version: str
    compensation_id: OpaqueId
    original_operation_id: OpaqueId
    kind: CompensationKind
    state: CompensationState
    version: int
    intent_digest: str
    arguments_mode: ArgumentsMode
    arguments: JsonValue | None
    arguments_ref: str | None
    idempotency_identity: str
    requested_by: PrincipalRef
    policy_decision_id: OpaqueId | None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "Compensation.contract_version must be v1",
            )
        if self.kind is CompensationKind.NONE:
            raise ContractValidationError(
                "illegal_combination",
                "Compensation.kind must not be NONE",
            )
        if self.version < INITIAL_COMPENSATION_VERSION:
            raise ContractValidationError(
                "invalid_range",
                "Compensation.version must be >= 1",
            )
        if self.arguments_mode is ArgumentsMode.INLINE:
            if self.arguments is None or self.arguments_ref is not None:
                raise ContractValidationError(
                    "illegal_combination",
                    "INLINE compensation requires arguments and forbids arguments_ref",
                )
            reject_secrets_in_json(self.arguments, field="Compensation.arguments")
        elif self.arguments is not None or self.arguments_ref is None:
            raise ContractValidationError(
                "illegal_combination",
                "REFERENCE compensation requires arguments_ref and forbids arguments",
            )
        expected = compensation_idempotency_identity(self.compensation_id)
        if self.idempotency_identity != expected:
            raise ContractValidationError(
                "idempotency_mismatch",
                "idempotency_identity must be sb:v1:comp:{compensation_id}",
            )
        if self.updated_at.value < self.created_at.value:
            raise ContractValidationError(
                "invalid_timestamp",
                "updated_at must not precede created_at",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "compensation_id": self.compensation_id.to_wire(),
            "original_operation_id": self.original_operation_id.to_wire(),
            "kind": self.kind.value,
            "state": self.state.value,
            "version": self.version,
            "intent_digest": self.intent_digest,
            "arguments_mode": self.arguments_mode.value,
            "arguments": (
                None if self.arguments is None else json_to_plain(self.arguments)
            ),
            "arguments_ref": self.arguments_ref,
            "idempotency_identity": self.idempotency_identity,
            "requested_by": self.requested_by.to_wire(),
            "policy_decision_id": (
                None
                if self.policy_decision_id is None
                else self.policy_decision_id.to_wire()
            ),
            "created_at": self.created_at.to_wire(),
            "updated_at": self.updated_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> Compensation:
        data = require_mapping(raw, type_name="Compensation")
        reject_unknown_keys(data, _COMP_FIELDS, type_name="Compensation")
        parse_contract_version(
            require_key(data, "contract_version", type_name="Compensation"),
            type_name="Compensation",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            compensation_id=OpaqueId.from_wire(
                require_key(data, "compensation_id", type_name="Compensation"),
                field="Compensation.compensation_id",
            ),
            original_operation_id=OpaqueId.from_wire(
                require_key(data, "original_operation_id", type_name="Compensation"),
                field="Compensation.original_operation_id",
            ),
            kind=parse_enum(
                CompensationKind,
                require_key(data, "kind", type_name="Compensation"),
                field="Compensation.kind",
            ),
            state=parse_enum(
                CompensationState,
                require_key(data, "state", type_name="Compensation"),
                field="Compensation.state",
            ),
            version=parse_int(
                require_key(data, "version", type_name="Compensation"),
                field="Compensation.version",
                minimum=1,
            ),
            intent_digest=parse_str(
                require_key(data, "intent_digest", type_name="Compensation"),
                field="Compensation.intent_digest",
            ),
            arguments_mode=parse_enum(
                ArgumentsMode,
                require_key(data, "arguments_mode", type_name="Compensation"),
                field="Compensation.arguments_mode",
            ),
            arguments=parse_optional_json_value(
                optional_key(data, "arguments"),
                field="Compensation.arguments",
            ),
            arguments_ref=parse_optional_str(
                optional_key(data, "arguments_ref"),
                field="Compensation.arguments_ref",
            ),
            idempotency_identity=parse_str(
                require_key(data, "idempotency_identity", type_name="Compensation"),
                field="Compensation.idempotency_identity",
            ),
            requested_by=PrincipalRef.from_wire(
                require_key(data, "requested_by", type_name="Compensation")
            ),
            policy_decision_id=parse_optional_opaque_id(
                optional_key(data, "policy_decision_id"),
                field="Compensation.policy_decision_id",
            ),
            created_at=UtcTimestamp.from_wire(
                require_key(data, "created_at", type_name="Compensation"),
                field="Compensation.created_at",
            ),
            updated_at=UtcTimestamp.from_wire(
                require_key(data, "updated_at", type_name="Compensation"),
                field="Compensation.updated_at",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationAttempt:
    contract_version: str
    compensation_attempt_id: OpaqueId
    compensation_id: OpaqueId
    attempt_number: int
    state: AttemptState
    started_at: UtcTimestamp
    completed_at: UtcTimestamp | None
    provider_idempotency_key: str | None
    external_operation_id: str | None
    outcome: EffectOutcome | None
    evidence: ProviderEvidence | None
    error: NormalizedError | None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "CompensationAttempt.contract_version must be v1",
            )
        if self.attempt_number < 1:
            raise ContractValidationError(
                "invalid_range",
                "attempt_number must be >= 1",
            )
        if self.state is AttemptState.STARTED:
            if self.completed_at is not None or self.outcome is not None:
                raise ContractValidationError(
                    "illegal_combination",
                    "STARTED compensation attempt must not have completed_at or outcome",
                )
        elif self.state is AttemptState.COMPLETED:
            if self.completed_at is None or self.outcome is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "COMPLETED compensation attempt requires completed_at and outcome",
                )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "compensation_attempt_id": self.compensation_attempt_id.to_wire(),
            "compensation_id": self.compensation_id.to_wire(),
            "attempt_number": self.attempt_number,
            "state": self.state.value,
            "started_at": self.started_at.to_wire(),
            "completed_at": (
                None if self.completed_at is None else self.completed_at.to_wire()
            ),
            "provider_idempotency_key": self.provider_idempotency_key,
            "external_operation_id": self.external_operation_id,
            "outcome": None if self.outcome is None else self.outcome.value,
            "evidence": None if self.evidence is None else self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> CompensationAttempt:
        data = require_mapping(raw, type_name="CompensationAttempt")
        reject_unknown_keys(data, _ATTEMPT_FIELDS, type_name="CompensationAttempt")
        parse_contract_version(
            require_key(data, "contract_version", type_name="CompensationAttempt"),
            type_name="CompensationAttempt",
        )
        completed_raw = optional_key(data, "completed_at")
        return cls(
            contract_version=CONTRACT_VERSION,
            compensation_attempt_id=OpaqueId.from_wire(
                require_key(
                    data, "compensation_attempt_id", type_name="CompensationAttempt"
                ),
                field="CompensationAttempt.compensation_attempt_id",
            ),
            compensation_id=OpaqueId.from_wire(
                require_key(data, "compensation_id", type_name="CompensationAttempt"),
                field="CompensationAttempt.compensation_id",
            ),
            attempt_number=parse_int(
                require_key(data, "attempt_number", type_name="CompensationAttempt"),
                field="CompensationAttempt.attempt_number",
                minimum=1,
            ),
            state=parse_enum(
                AttemptState,
                require_key(data, "state", type_name="CompensationAttempt"),
                field="CompensationAttempt.state",
            ),
            started_at=UtcTimestamp.from_wire(
                require_key(data, "started_at", type_name="CompensationAttempt"),
                field="CompensationAttempt.started_at",
            ),
            completed_at=(
                None
                if completed_raw is None
                else UtcTimestamp.from_wire(
                    completed_raw, field="CompensationAttempt.completed_at"
                )
            ),
            provider_idempotency_key=parse_optional_str(
                optional_key(data, "provider_idempotency_key"),
                field="CompensationAttempt.provider_idempotency_key",
            ),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="CompensationAttempt.external_operation_id",
            ),
            outcome=parse_optional_enum(
                EffectOutcome,
                optional_key(data, "outcome"),
                field="CompensationAttempt.outcome",
            ),
            evidence=parse_optional_evidence(optional_key(data, "evidence")),
            error=parse_optional_error(optional_key(data, "error")),
        )
