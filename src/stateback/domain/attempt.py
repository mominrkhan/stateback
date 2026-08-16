"""ExecutionAttempt — `contracts/OPERATION_CONTRACT.md` §7."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import CONTRACT_VERSION, AttemptState, EffectOutcome
from stateback.domain.errors import NormalizedError, parse_optional_error
from stateback.domain.evidence import ProviderEvidence, parse_optional_evidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_optional_enum,
    parse_optional_str,
    parse_str_list,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_FIELDS = frozenset(
    {
        "contract_version",
        "attempt_id",
        "operation_id",
        "attempt_number",
        "state",
        "started_at",
        "completed_at",
        "provider_idempotency_key",
        "external_operation_id",
        "external_resource_ids",
        "outcome",
        "evidence",
        "error",
        "correlation_id",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAttempt:
    contract_version: str
    attempt_id: OpaqueId
    operation_id: OpaqueId
    attempt_number: int
    state: AttemptState
    started_at: UtcTimestamp
    completed_at: UtcTimestamp | None
    provider_idempotency_key: str | None
    external_operation_id: str | None
    external_resource_ids: tuple[str, ...]
    outcome: EffectOutcome | None
    evidence: ProviderEvidence | None
    error: NormalizedError | None
    correlation_id: str | None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "ExecutionAttempt.contract_version must be v1",
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
                    "STARTED attempt must not have completed_at or outcome",
                )
        elif self.state is AttemptState.COMPLETED:
            if self.completed_at is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "COMPLETED attempt requires completed_at",
                )
            if self.outcome is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "COMPLETED attempt requires outcome",
                )
            if self.completed_at.value < self.started_at.value:
                raise ContractValidationError(
                    "invalid_timestamp",
                    "completed_at must not precede started_at",
                )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "attempt_id": self.attempt_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "attempt_number": self.attempt_number,
            "state": self.state.value,
            "started_at": self.started_at.to_wire(),
            "completed_at": (
                None if self.completed_at is None else self.completed_at.to_wire()
            ),
            "provider_idempotency_key": self.provider_idempotency_key,
            "external_operation_id": self.external_operation_id,
            "external_resource_ids": list(self.external_resource_ids),
            "outcome": None if self.outcome is None else self.outcome.value,
            "evidence": None if self.evidence is None else self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_wire(cls, raw: object) -> ExecutionAttempt:
        data = require_mapping(raw, type_name="ExecutionAttempt")
        reject_unknown_keys(data, _FIELDS, type_name="ExecutionAttempt")
        parse_contract_version(
            require_key(data, "contract_version", type_name="ExecutionAttempt"),
            type_name="ExecutionAttempt",
        )
        completed_raw = optional_key(data, "completed_at")
        return cls(
            contract_version=CONTRACT_VERSION,
            attempt_id=OpaqueId.from_wire(
                require_key(data, "attempt_id", type_name="ExecutionAttempt"),
                field="ExecutionAttempt.attempt_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="ExecutionAttempt"),
                field="ExecutionAttempt.operation_id",
            ),
            attempt_number=parse_int(
                require_key(data, "attempt_number", type_name="ExecutionAttempt"),
                field="ExecutionAttempt.attempt_number",
                minimum=1,
            ),
            state=parse_enum(
                AttemptState,
                require_key(data, "state", type_name="ExecutionAttempt"),
                field="ExecutionAttempt.state",
            ),
            started_at=UtcTimestamp.from_wire(
                require_key(data, "started_at", type_name="ExecutionAttempt"),
                field="ExecutionAttempt.started_at",
            ),
            completed_at=(
                None
                if completed_raw is None
                else UtcTimestamp.from_wire(
                    completed_raw, field="ExecutionAttempt.completed_at"
                )
            ),
            provider_idempotency_key=parse_optional_str(
                optional_key(data, "provider_idempotency_key"),
                field="ExecutionAttempt.provider_idempotency_key",
            ),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="ExecutionAttempt.external_operation_id",
            ),
            external_resource_ids=parse_str_list(
                require_key(
                    data, "external_resource_ids", type_name="ExecutionAttempt"
                ),
                field="ExecutionAttempt.external_resource_ids",
            ),
            outcome=parse_optional_enum(
                EffectOutcome,
                optional_key(data, "outcome"),
                field="ExecutionAttempt.outcome",
            ),
            evidence=parse_optional_evidence(optional_key(data, "evidence")),
            error=parse_optional_error(optional_key(data, "error")),
            correlation_id=parse_optional_str(
                optional_key(data, "correlation_id"),
                field="ExecutionAttempt.correlation_id",
            ),
        )
