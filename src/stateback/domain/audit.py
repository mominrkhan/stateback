"""AuditEvent — `contracts/AUDIT_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    AuditEventType,
    OperationState,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue, json_to_plain, parse_json_value
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

_FIELDS = frozenset(
    {
        "contract_version",
        "audit_event_id",
        "operation_id",
        "sequence",
        "event_type",
        "from_state",
        "to_state",
        "operation_version",
        "actor",
        "reason_code",
        "data",
        "correlation_id",
        "created_at",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEvent:
    contract_version: str
    audit_event_id: OpaqueId
    operation_id: OpaqueId
    sequence: int
    event_type: AuditEventType
    from_state: OperationState | None
    to_state: OperationState | None
    operation_version: int
    actor: PrincipalRef | None
    reason_code: str
    data: JsonValue
    correlation_id: str | None
    created_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "AuditEvent.contract_version must be v1",
            )
        if self.sequence < 1:
            raise ContractValidationError(
                "invalid_range",
                "AuditEvent.sequence must be >= 1",
            )
        if self.operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "operation_version must be >= 1",
            )
        reject_secrets_in_json(self.data, field="AuditEvent.data")
        if self.event_type is AuditEventType.OPERATION_TRANSITIONED:
            if self.from_state is None or self.to_state is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "transition audit events require from_state and to_state",
                )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "audit_event_id": self.audit_event_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "from_state": None if self.from_state is None else self.from_state.value,
            "to_state": None if self.to_state is None else self.to_state.value,
            "operation_version": self.operation_version,
            "actor": None if self.actor is None else self.actor.to_wire(),
            "reason_code": self.reason_code,
            "data": json_to_plain(self.data),
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> AuditEvent:
        data = require_mapping(raw, type_name="AuditEvent")
        reject_unknown_keys(data, _FIELDS, type_name="AuditEvent")
        parse_contract_version(
            require_key(data, "contract_version", type_name="AuditEvent"),
            type_name="AuditEvent",
        )
        actor_raw = optional_key(data, "actor")
        return cls(
            contract_version=CONTRACT_VERSION,
            audit_event_id=OpaqueId.from_wire(
                require_key(data, "audit_event_id", type_name="AuditEvent"),
                field="AuditEvent.audit_event_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="AuditEvent"),
                field="AuditEvent.operation_id",
            ),
            sequence=parse_int(
                require_key(data, "sequence", type_name="AuditEvent"),
                field="AuditEvent.sequence",
                minimum=1,
            ),
            event_type=parse_enum(
                AuditEventType,
                require_key(data, "event_type", type_name="AuditEvent"),
                field="AuditEvent.event_type",
            ),
            from_state=parse_optional_enum(
                OperationState,
                optional_key(data, "from_state"),
                field="AuditEvent.from_state",
            ),
            to_state=parse_optional_enum(
                OperationState,
                optional_key(data, "to_state"),
                field="AuditEvent.to_state",
            ),
            operation_version=parse_int(
                require_key(data, "operation_version", type_name="AuditEvent"),
                field="AuditEvent.operation_version",
                minimum=1,
            ),
            actor=None if actor_raw is None else PrincipalRef.from_wire(actor_raw),
            reason_code=parse_str(
                require_key(data, "reason_code", type_name="AuditEvent"),
                field="AuditEvent.reason_code",
            ),
            data=parse_json_value(
                require_key(data, "data", type_name="AuditEvent"),
                field="AuditEvent.data",
            ),
            correlation_id=parse_optional_str(
                optional_key(data, "correlation_id"),
                field="AuditEvent.correlation_id",
            ),
            created_at=UtcTimestamp.from_wire(
                require_key(data, "created_at", type_name="AuditEvent"),
                field="AuditEvent.created_at",
            ),
        )
