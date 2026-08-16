"""Audit event construction for the transition engine."""

from __future__ import annotations

from stateback.domain.audit import AuditEvent
from stateback.domain.enums import CONTRACT_VERSION, AuditEventType, OperationState
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp

ALLOWED_AUDIT_DATA_KEYS = frozenset(
    {
        "kind",
        "policy_decision_id",
        "approval_id",
        "attempt_id",
        "verification_id",
        "compensation_id",
        "compensation_attempt_id",
        "reconciliation_decision_id",
        "effect_outcome",
        "retry_safety_reason",
        "crash_interpretation",
    }
)


def build_audit_event(
    *,
    audit_event_id: OpaqueId,
    operation_id: OpaqueId,
    sequence: int,
    event_type: AuditEventType,
    from_state: OperationState | None,
    to_state: OperationState | None,
    operation_version: int,
    actor: PrincipalRef | None,
    reason_code: str,
    data: JsonValue,
    correlation_id: str | None,
    created_at: UtcTimestamp,
) -> AuditEvent:
    return AuditEvent(
        contract_version=CONTRACT_VERSION,
        audit_event_id=audit_event_id,
        operation_id=operation_id,
        sequence=sequence,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        operation_version=operation_version,
        actor=actor,
        reason_code=reason_code,
        data=data,
        correlation_id=correlation_id,
        created_at=created_at,
    )
