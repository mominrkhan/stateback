"""Caller-supplied opaque IDs for compensation. Callers inject every ID."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from stateback.domain.ids import OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationRetryIds:
    parent_retry_transition_audit_event_id: OpaqueId
    parent_retry_outbox_event_id: OpaqueId
    attempt_id: OpaqueId
    attempt_audit_event_id: OpaqueId
    attempt_outbox_event_id: OpaqueId
    resume_verification_id: OpaqueId
    resume_verification_start_audit_event_id: OpaqueId
    resume_verification_complete_audit_event_id: OpaqueId
    resume_verification_outbox_event_id: OpaqueId
    resume_complete_transition_audit_event_id: OpaqueId
    resume_complete_outbox_event_id: OpaqueId
    evidence_audit_event_id: OpaqueId
    complete_transition_audit_event_id: OpaqueId
    complete_outbox_event_id: OpaqueId
    verification_id: OpaqueId
    verification_start_audit_event_id: OpaqueId
    verification_complete_audit_event_id: OpaqueId
    verification_outbox_event_id: OpaqueId


class CompensationRetryIdFactory(Protocol):
    def for_attempt(
        self, compensation_id: OpaqueId, attempt_number: int
    ) -> CompensationRetryIds: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationIds:
    compensation_id: OpaqueId
    compensation_attempt_id: OpaqueId
    start_transition_audit_event_id: OpaqueId
    compensation_requested_audit_event_id: OpaqueId
    start_outbox_event_id: OpaqueId
    claim_attempt_audit_event_id: OpaqueId
    evidence_audit_event_id: OpaqueId
    complete_transition_audit_event_id: OpaqueId
    complete_outbox_event_id: OpaqueId
    verification_id: OpaqueId
    verification_start_audit_event_id: OpaqueId
    verification_complete_audit_event_id: OpaqueId
    verification_outbox_event_id: OpaqueId
    manual_audit_event_id: OpaqueId
    operator_audit_event_id: OpaqueId
    retry_ids_for: CompensationRetryIdFactory
