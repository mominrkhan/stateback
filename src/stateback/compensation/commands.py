"""Compensation command dataclasses. Callers inject every ID."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from stateback.compensation.ids import CompensationIds
from stateback.domain.enums import PrincipalType
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef

COMPENSATION_ACTOR = PrincipalRef(
    type=PrincipalType.SERVICE,
    id="stateback.compensation",
    display_name="CompensationService",
)


@runtime_checkable
class CompensationIdFactory(Protocol):
    def for_operation(self, operation_id: OpaqueId) -> CompensationIds: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StartCompensationCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: CompensationIds
    actor: PrincipalRef | None
    correlation_id: str | None
    automatic: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteCompensationCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: CompensationIds
    actor: PrincipalRef | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverCompensationCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: CompensationIds
    actor: PrincipalRef | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScanCompensationCommand:
    ids_for: CompensationIdFactory
    actor: PrincipalRef | None
    correlation_id: str | None
    limit: int | None

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be >= 1 when set")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatorCompensationCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: CompensationIds
    actor: PrincipalRef
    correlation_id: str | None
    reason_code: str
