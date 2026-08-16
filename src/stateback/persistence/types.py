from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from stateback.domain.enums import (
    ApprovalState,
    ArgumentsMode,
    AttemptState,
    AuditEventType,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    OperationState,
    OutboxState,
    PolicyVerdict,
    ReconciliationAction,
    RiskLevel,
    VerificationTarget,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.domain.time import UtcTimestamp
from stateback.persistence.exceptions import MalformedRowError

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

OPERATION_STATES: tuple[str, ...] = tuple(member.value for member in OperationState)
ATTEMPT_STATES: tuple[str, ...] = tuple(member.value for member in AttemptState)
EFFECT_OUTCOMES: tuple[str, ...] = tuple(member.value for member in EffectOutcome)
RISK_LEVELS: tuple[str, ...] = tuple(member.value for member in RiskLevel)
POLICY_VERDICTS: tuple[str, ...] = tuple(member.value for member in PolicyVerdict)
APPROVAL_STATES: tuple[str, ...] = tuple(member.value for member in ApprovalState)
COMPENSATION_KINDS: tuple[str, ...] = (
    CompensationKind.EXACT.value,
    CompensationKind.APPROXIMATE.value,
    CompensationKind.MITIGATING.value,
)
COMPENSATION_STATES: tuple[str, ...] = tuple(
    member.value for member in CompensationState
)
VERIFICATION_TARGETS: tuple[str, ...] = tuple(
    member.value for member in VerificationTarget
)
OUTBOX_STATES: tuple[str, ...] = tuple(member.value for member in OutboxState)
WORK_COMMANDS: tuple[str, ...] = tuple(member.value for member in WorkCommand)
ARGUMENTS_MODES: tuple[str, ...] = tuple(member.value for member in ArgumentsMode)
RECONCILIATION_ACTIONS: tuple[str, ...] = tuple(
    member.value for member in ReconciliationAction
)
AUDIT_EVENT_TYPES: tuple[str, ...] = tuple(member.value for member in AuditEventType)


def opaque_to_uuid(opaque: OpaqueId) -> uuid.UUID:
    return uuid.UUID(opaque.value)


def uuid_to_opaque(value: uuid.UUID) -> OpaqueId:
    return OpaqueId(value=str(value))


def utc_from_db(value: datetime) -> UtcTimestamp:
    if value.tzinfo is None:
        raise MalformedRowError("timestamp must be timezone-aware UTC")
    return UtcTimestamp(value=value.astimezone(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredReconciliationDecision:
    reconciliation_decision_id: OpaqueId
    operation_id: OpaqueId
    operation_version: int
    verification_id: OpaqueId | None
    decision: ReconciliationDecision
    created_at: UtcTimestamp
