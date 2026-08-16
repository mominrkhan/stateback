"""Operation aggregate — `contracts/OPERATION_CONTRACT.md` §5."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    INITIAL_OPERATION_VERSION,
    OperationState,
    RiskLevel,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId, parse_optional_opaque_id
from stateback.domain.intent import IntentEnvelope, operation_idempotency_identity
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_FIELDS = frozenset(
    {
        "contract_version",
        "operation_id",
        "state",
        "version",
        "intent",
        "risk_level",
        "idempotency_identity",
        "current_policy_decision_id",
        "current_approval_id",
        "latest_attempt_id",
        "latest_verification_id",
        "compensation_id",
        "created_at",
        "updated_at",
    }
)


def next_version(current: int) -> int:
    if isinstance(current, bool) or not isinstance(current, int) or current < 1:
        raise ContractValidationError(
            "invalid_range",
            "version must be an integer >= 1",
        )
    return current + 1


@dataclass(frozen=True, slots=True, kw_only=True)
class Operation:
    contract_version: str
    operation_id: OpaqueId
    state: OperationState
    version: int
    intent: IntentEnvelope
    risk_level: RiskLevel
    idempotency_identity: str
    current_policy_decision_id: OpaqueId | None
    current_approval_id: OpaqueId | None
    latest_attempt_id: OpaqueId | None
    latest_verification_id: OpaqueId | None
    compensation_id: OpaqueId | None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "Operation.contract_version must be v1",
            )
        if self.version < INITIAL_OPERATION_VERSION:
            raise ContractValidationError(
                "invalid_range",
                "Operation.version must be >= 1",
            )
        expected = operation_idempotency_identity(self.operation_id)
        if self.idempotency_identity != expected:
            raise ContractValidationError(
                "idempotency_mismatch",
                "idempotency_identity must be sb:v1:op:{operation_id}",
            )
        if self.updated_at.value < self.created_at.value:
            raise ContractValidationError(
                "invalid_timestamp",
                "updated_at must not precede created_at",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "operation_id": self.operation_id.to_wire(),
            "state": self.state.value,
            "version": self.version,
            "intent": self.intent.to_wire(),
            "risk_level": self.risk_level.value,
            "idempotency_identity": self.idempotency_identity,
            "current_policy_decision_id": (
                None
                if self.current_policy_decision_id is None
                else self.current_policy_decision_id.to_wire()
            ),
            "current_approval_id": (
                None
                if self.current_approval_id is None
                else self.current_approval_id.to_wire()
            ),
            "latest_attempt_id": (
                None
                if self.latest_attempt_id is None
                else self.latest_attempt_id.to_wire()
            ),
            "latest_verification_id": (
                None
                if self.latest_verification_id is None
                else self.latest_verification_id.to_wire()
            ),
            "compensation_id": (
                None if self.compensation_id is None else self.compensation_id.to_wire()
            ),
            "created_at": self.created_at.to_wire(),
            "updated_at": self.updated_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> Operation:
        data = require_mapping(raw, type_name="Operation")
        reject_unknown_keys(data, _FIELDS, type_name="Operation")
        parse_contract_version(
            require_key(data, "contract_version", type_name="Operation"),
            type_name="Operation",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="Operation"),
                field="Operation.operation_id",
            ),
            state=parse_enum(
                OperationState,
                require_key(data, "state", type_name="Operation"),
                field="Operation.state",
            ),
            version=parse_int(
                require_key(data, "version", type_name="Operation"),
                field="Operation.version",
                minimum=1,
            ),
            intent=IntentEnvelope.from_wire(
                require_key(data, "intent", type_name="Operation")
            ),
            risk_level=parse_enum(
                RiskLevel,
                require_key(data, "risk_level", type_name="Operation"),
                field="Operation.risk_level",
            ),
            idempotency_identity=parse_str(
                require_key(data, "idempotency_identity", type_name="Operation"),
                field="Operation.idempotency_identity",
            ),
            current_policy_decision_id=parse_optional_opaque_id(
                optional_key(data, "current_policy_decision_id"),
                field="Operation.current_policy_decision_id",
            ),
            current_approval_id=parse_optional_opaque_id(
                optional_key(data, "current_approval_id"),
                field="Operation.current_approval_id",
            ),
            latest_attempt_id=parse_optional_opaque_id(
                optional_key(data, "latest_attempt_id"),
                field="Operation.latest_attempt_id",
            ),
            latest_verification_id=parse_optional_opaque_id(
                optional_key(data, "latest_verification_id"),
                field="Operation.latest_verification_id",
            ),
            compensation_id=parse_optional_opaque_id(
                optional_key(data, "compensation_id"),
                field="Operation.compensation_id",
            ),
            created_at=UtcTimestamp.from_wire(
                require_key(data, "created_at", type_name="Operation"),
                field="Operation.created_at",
            ),
            updated_at=UtcTimestamp.from_wire(
                require_key(data, "updated_at", type_name="Operation"),
                field="Operation.updated_at",
            ),
        )
