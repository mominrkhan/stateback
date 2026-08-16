"""Caller-supplied opaque IDs for submit, execute, and recover."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.ids import OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitIds:
    operation_id: OpaqueId
    created_audit_event_id: OpaqueId
    policy_decision_id: OpaqueId
    policy_audit_event_id: OpaqueId
    policy_transition_audit_event_id: OpaqueId
    allow_outbox_event_id: OpaqueId
    approval_id: OpaqueId
    approval_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteIds:
    attempt_id: OpaqueId
    claim_transition_audit_event_id: OpaqueId
    attempt_audit_event_id: OpaqueId
    evidence_audit_event_id: OpaqueId
    execution_transition_audit_event_id: OpaqueId
    execution_outbox_event_id: OpaqueId
    verification_id: OpaqueId
    verification_audit_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverIds:
    evidence_audit_event_id: OpaqueId
    execution_transition_audit_event_id: OpaqueId
    execution_outbox_event_id: OpaqueId
    verification_id: OpaqueId
    verification_audit_event_id: OpaqueId
