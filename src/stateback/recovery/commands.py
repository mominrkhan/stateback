"""Recovery command dataclasses. Callers inject every ID."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from stateback.domain.enums import PrincipalType
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef
from stateback.recovery.ids import RecoveryIds

RECOVERY_ACTOR = PrincipalRef(
    type=PrincipalType.SERVICE,
    id="stateback.recovery",
    display_name="RecoveryService",
)


@runtime_checkable
class RecoveryIdFactory(Protocol):
    def for_operation(self, operation_id: OpaqueId) -> RecoveryIds: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: RecoveryIds
    actor: PrincipalRef | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScanCommand:
    ids_for: RecoveryIdFactory
    actor: PrincipalRef | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatorVerificationCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: RecoveryIds
    actor: PrincipalRef
    reason_code: str
    correlation_id: str | None
