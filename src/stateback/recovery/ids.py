"""Caller-supplied opaque IDs for recovery. Nested RecoverIds cover leftover EXECUTING."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.ids import OpaqueId
from stateback.runtime.ids import RecoverIds


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryIds:
    verification_id: OpaqueId
    verification_start_audit_event_id: OpaqueId
    verification_complete_audit_event_id: OpaqueId
    start_transition_audit_event_id: OpaqueId
    start_outbox_event_id: OpaqueId
    complete_transition_audit_event_id: OpaqueId
    retry_outbox_event_id: OpaqueId
    manual_audit_event_id: OpaqueId
    reconciliation_decision_id: OpaqueId
    reconciliation_audit_event_id: OpaqueId
    execution_recover: RecoverIds
