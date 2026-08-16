"""Outbox and work-message types — `contracts/MESSAGING_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import CONTRACT_VERSION, OutboxState, WorkCommand
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_optional_str,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_OUTBOX_FIELDS = frozenset(
    {
        "contract_version",
        "event_id",
        "state",
        "aggregate_type",
        "aggregate_id",
        "operation_version",
        "command",
        "created_at",
        "published_at",
        "correlation_id",
    }
)
_MESSAGE_FIELDS = frozenset(
    {
        "contract_version",
        "message_id",
        "outbox_event_id",
        "operation_id",
        "expected_operation_version",
        "command",
        "correlation_id",
        "created_at",
    }
)
AGGREGATE_TYPE_OPERATION = "operation"


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxEvent:
    contract_version: str
    event_id: OpaqueId
    state: OutboxState
    aggregate_type: str
    aggregate_id: OpaqueId
    operation_version: int
    command: WorkCommand
    created_at: UtcTimestamp
    published_at: UtcTimestamp | None
    correlation_id: str | None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "OutboxEvent.contract_version must be v1",
            )
        if self.aggregate_type != AGGREGATE_TYPE_OPERATION:
            raise ContractValidationError(
                "illegal_combination",
                "OutboxEvent.aggregate_type must be 'operation' in v1",
            )
        if self.operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "operation_version must be >= 1",
            )
        if self.state is OutboxState.PENDING and self.published_at is not None:
            raise ContractValidationError(
                "illegal_combination",
                "PENDING outbox events must not have published_at",
            )
        if self.state is OutboxState.PUBLISHED and self.published_at is None:
            raise ContractValidationError(
                "illegal_combination",
                "PUBLISHED outbox events require published_at",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "event_id": self.event_id.to_wire(),
            "state": self.state.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id.to_wire(),
            "operation_version": self.operation_version,
            "command": self.command.value,
            "created_at": self.created_at.to_wire(),
            "published_at": (
                None if self.published_at is None else self.published_at.to_wire()
            ),
            "correlation_id": self.correlation_id,
        }

    @classmethod
    def from_wire(cls, raw: object) -> OutboxEvent:
        data = require_mapping(raw, type_name="OutboxEvent")
        reject_unknown_keys(data, _OUTBOX_FIELDS, type_name="OutboxEvent")
        parse_contract_version(
            require_key(data, "contract_version", type_name="OutboxEvent"),
            type_name="OutboxEvent",
        )
        published_raw = optional_key(data, "published_at")
        return cls(
            contract_version=CONTRACT_VERSION,
            event_id=OpaqueId.from_wire(
                require_key(data, "event_id", type_name="OutboxEvent"),
                field="OutboxEvent.event_id",
            ),
            state=parse_enum(
                OutboxState,
                require_key(data, "state", type_name="OutboxEvent"),
                field="OutboxEvent.state",
            ),
            aggregate_type=parse_str(
                require_key(data, "aggregate_type", type_name="OutboxEvent"),
                field="OutboxEvent.aggregate_type",
            ),
            aggregate_id=OpaqueId.from_wire(
                require_key(data, "aggregate_id", type_name="OutboxEvent"),
                field="OutboxEvent.aggregate_id",
            ),
            operation_version=parse_int(
                require_key(data, "operation_version", type_name="OutboxEvent"),
                field="OutboxEvent.operation_version",
                minimum=1,
            ),
            command=parse_enum(
                WorkCommand,
                require_key(data, "command", type_name="OutboxEvent"),
                field="OutboxEvent.command",
            ),
            created_at=UtcTimestamp.from_wire(
                require_key(data, "created_at", type_name="OutboxEvent"),
                field="OutboxEvent.created_at",
            ),
            published_at=(
                None
                if published_raw is None
                else UtcTimestamp.from_wire(
                    published_raw, field="OutboxEvent.published_at"
                )
            ),
            correlation_id=parse_optional_str(
                optional_key(data, "correlation_id"),
                field="OutboxEvent.correlation_id",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkMessageV1:
    contract_version: str
    message_id: OpaqueId
    outbox_event_id: OpaqueId
    operation_id: OpaqueId
    expected_operation_version: int
    command: WorkCommand
    correlation_id: str | None
    created_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "WorkMessageV1.contract_version must be v1",
            )
        if self.expected_operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "expected_operation_version must be >= 1",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "message_id": self.message_id.to_wire(),
            "outbox_event_id": self.outbox_event_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "expected_operation_version": self.expected_operation_version,
            "command": self.command.value,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> WorkMessageV1:
        data = require_mapping(raw, type_name="WorkMessageV1")
        reject_unknown_keys(data, _MESSAGE_FIELDS, type_name="WorkMessageV1")
        parse_contract_version(
            require_key(data, "contract_version", type_name="WorkMessageV1"),
            type_name="WorkMessageV1",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            message_id=OpaqueId.from_wire(
                require_key(data, "message_id", type_name="WorkMessageV1"),
                field="WorkMessageV1.message_id",
            ),
            outbox_event_id=OpaqueId.from_wire(
                require_key(data, "outbox_event_id", type_name="WorkMessageV1"),
                field="WorkMessageV1.outbox_event_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="WorkMessageV1"),
                field="WorkMessageV1.operation_id",
            ),
            expected_operation_version=parse_int(
                require_key(
                    data, "expected_operation_version", type_name="WorkMessageV1"
                ),
                field="WorkMessageV1.expected_operation_version",
                minimum=1,
            ),
            command=parse_enum(
                WorkCommand,
                require_key(data, "command", type_name="WorkMessageV1"),
                field="WorkMessageV1.command",
            ),
            correlation_id=parse_optional_str(
                optional_key(data, "correlation_id"),
                field="WorkMessageV1.correlation_id",
            ),
            created_at=UtcTimestamp.from_wire(
                require_key(data, "created_at", type_name="WorkMessageV1"),
                field="WorkMessageV1.created_at",
            ),
        )
