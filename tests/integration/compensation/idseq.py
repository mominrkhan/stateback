from __future__ import annotations

from stateback.compensation.ids import CompensationIds, CompensationRetryIds
from stateback.domain.ids import OpaqueId
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

__all__ = [
    "IdSeq",
    "SeqCompensationIds",
    "compensation_ids",
    "execute_ids",
    "submit_ids",
]


def compensation_ids(seq: IdSeq) -> CompensationIds:
    return CompensationIds(
        compensation_id=seq.next(),
        compensation_attempt_id=seq.next(),
        start_transition_audit_event_id=seq.next(),
        compensation_requested_audit_event_id=seq.next(),
        start_outbox_event_id=seq.next(),
        claim_attempt_audit_event_id=seq.next(),
        evidence_audit_event_id=seq.next(),
        complete_transition_audit_event_id=seq.next(),
        complete_outbox_event_id=seq.next(),
        verification_id=seq.next(),
        verification_start_audit_event_id=seq.next(),
        verification_complete_audit_event_id=seq.next(),
        verification_outbox_event_id=seq.next(),
        manual_audit_event_id=seq.next(),
        operator_audit_event_id=seq.next(),
        retry_ids_for=SeqCompensationRetryIds(seq),
    )


class SeqCompensationRetryIds:
    def __init__(self, seq: IdSeq) -> None:
        self._seq = seq
        self._ids: dict[tuple[OpaqueId, int], CompensationRetryIds] = {}

    def for_attempt(
        self, compensation_id: OpaqueId, attempt_number: int
    ) -> CompensationRetryIds:
        if attempt_number < 2:
            raise ValueError("retry attempt_number must be >= 2")
        key = (compensation_id, attempt_number)
        existing = self._ids.get(key)
        if existing is not None:
            return existing
        ids = CompensationRetryIds(
            parent_retry_transition_audit_event_id=self._seq.next(),
            parent_retry_outbox_event_id=self._seq.next(),
            attempt_id=self._seq.next(),
            attempt_audit_event_id=self._seq.next(),
            attempt_outbox_event_id=self._seq.next(),
            resume_verification_id=self._seq.next(),
            resume_verification_start_audit_event_id=self._seq.next(),
            resume_verification_complete_audit_event_id=self._seq.next(),
            resume_verification_outbox_event_id=self._seq.next(),
            resume_complete_transition_audit_event_id=self._seq.next(),
            resume_complete_outbox_event_id=self._seq.next(),
            evidence_audit_event_id=self._seq.next(),
            complete_transition_audit_event_id=self._seq.next(),
            complete_outbox_event_id=self._seq.next(),
            verification_id=self._seq.next(),
            verification_start_audit_event_id=self._seq.next(),
            verification_complete_audit_event_id=self._seq.next(),
            verification_outbox_event_id=self._seq.next(),
        )
        self._ids[key] = ids
        return ids


class SeqCompensationIds:
    def __init__(self, seq: IdSeq) -> None:
        self._seq = seq

    def for_operation(self, operation_id: OpaqueId) -> CompensationIds:
        del operation_id
        return compensation_ids(self._seq)
