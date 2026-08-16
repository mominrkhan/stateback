"""Verification request/result — `contracts/VERIFICATION_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    EffectOutcome,
    VerificationTarget,
)
from stateback.domain.errors import NormalizedError, parse_optional_error
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId, parse_optional_opaque_id
from stateback.domain.refs import EffectRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_optional_str,
    parse_str,
    parse_str_list,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_REQUEST_FIELDS = frozenset(
    {
        "contract_version",
        "verification_id",
        "operation_id",
        "operation_version",
        "target",
        "target_attempt_id",
        "effect",
        "external_operation_id",
        "external_resource_ids",
        "idempotency_identity",
        "provider_evidence_refs",
        "requested_at",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "contract_version",
        "verification_id",
        "outcome",
        "evidence",
        "error",
        "completed_at",
    }
)


def _parse_opaque_id_list(raw: object, *, field: str) -> tuple[OpaqueId, ...]:
    if not isinstance(raw, list):
        raise ContractValidationError("invalid_type", f"{field} must be an array")
    return tuple(
        OpaqueId.from_wire(item, field=f"{field}[{index}]")
        for index, item in enumerate(raw)
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationRequest:
    contract_version: str
    verification_id: OpaqueId
    operation_id: OpaqueId
    operation_version: int
    target: VerificationTarget
    target_attempt_id: OpaqueId | None
    effect: EffectRef
    external_operation_id: str | None
    external_resource_ids: tuple[str, ...]
    idempotency_identity: str
    provider_evidence_refs: tuple[OpaqueId, ...]
    requested_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "VerificationRequest.contract_version must be v1",
            )
        if self.operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "operation_version must be >= 1",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "verification_id": self.verification_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "operation_version": self.operation_version,
            "target": self.target.value,
            "target_attempt_id": (
                None
                if self.target_attempt_id is None
                else self.target_attempt_id.to_wire()
            ),
            "effect": self.effect.to_wire(),
            "external_operation_id": self.external_operation_id,
            "external_resource_ids": list(self.external_resource_ids),
            "idempotency_identity": self.idempotency_identity,
            "provider_evidence_refs": [
                item.to_wire() for item in self.provider_evidence_refs
            ],
            "requested_at": self.requested_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> VerificationRequest:
        data = require_mapping(raw, type_name="VerificationRequest")
        reject_unknown_keys(data, _REQUEST_FIELDS, type_name="VerificationRequest")
        parse_contract_version(
            require_key(data, "contract_version", type_name="VerificationRequest"),
            type_name="VerificationRequest",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            verification_id=OpaqueId.from_wire(
                require_key(data, "verification_id", type_name="VerificationRequest"),
                field="VerificationRequest.verification_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="VerificationRequest"),
                field="VerificationRequest.operation_id",
            ),
            operation_version=parse_int(
                require_key(data, "operation_version", type_name="VerificationRequest"),
                field="VerificationRequest.operation_version",
                minimum=1,
            ),
            target=parse_enum(
                VerificationTarget,
                require_key(data, "target", type_name="VerificationRequest"),
                field="VerificationRequest.target",
            ),
            target_attempt_id=parse_optional_opaque_id(
                optional_key(data, "target_attempt_id"),
                field="VerificationRequest.target_attempt_id",
            ),
            effect=EffectRef.from_wire(
                require_key(data, "effect", type_name="VerificationRequest")
            ),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="VerificationRequest.external_operation_id",
            ),
            external_resource_ids=parse_str_list(
                require_key(
                    data, "external_resource_ids", type_name="VerificationRequest"
                ),
                field="VerificationRequest.external_resource_ids",
            ),
            idempotency_identity=parse_str(
                require_key(
                    data, "idempotency_identity", type_name="VerificationRequest"
                ),
                field="VerificationRequest.idempotency_identity",
            ),
            provider_evidence_refs=_parse_opaque_id_list(
                require_key(
                    data, "provider_evidence_refs", type_name="VerificationRequest"
                ),
                field="VerificationRequest.provider_evidence_refs",
            ),
            requested_at=UtcTimestamp.from_wire(
                require_key(data, "requested_at", type_name="VerificationRequest"),
                field="VerificationRequest.requested_at",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationResult:
    contract_version: str
    verification_id: OpaqueId
    outcome: EffectOutcome
    evidence: ProviderEvidence
    error: NormalizedError | None
    completed_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "VerificationResult.contract_version must be v1",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "verification_id": self.verification_id.to_wire(),
            "outcome": self.outcome.value,
            "evidence": self.evidence.to_wire(),
            "error": None if self.error is None else self.error.to_wire(),
            "completed_at": self.completed_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> VerificationResult:
        data = require_mapping(raw, type_name="VerificationResult")
        reject_unknown_keys(data, _RESULT_FIELDS, type_name="VerificationResult")
        parse_contract_version(
            require_key(data, "contract_version", type_name="VerificationResult"),
            type_name="VerificationResult",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            verification_id=OpaqueId.from_wire(
                require_key(data, "verification_id", type_name="VerificationResult"),
                field="VerificationResult.verification_id",
            ),
            outcome=parse_enum(
                EffectOutcome,
                require_key(data, "outcome", type_name="VerificationResult"),
                field="VerificationResult.outcome",
            ),
            evidence=ProviderEvidence.from_wire(
                require_key(data, "evidence", type_name="VerificationResult")
            ),
            error=parse_optional_error(optional_key(data, "error")),
            completed_at=UtcTimestamp.from_wire(
                require_key(data, "completed_at", type_name="VerificationResult"),
                field="VerificationResult.completed_at",
            ),
        )
