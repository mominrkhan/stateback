from __future__ import annotations

from stateback.domain.ids import OpaqueId
from stateback.runtime.ids import ExecuteIds, RecoverIds, SubmitIds


class IdSeq:
    def __init__(self, start: int = 0x20) -> None:
        self._n = start

    def next(self) -> OpaqueId:
        value = OpaqueId(value=f"00000000-0000-4000-8000-{self._n:012x}")
        self._n += 1
        return value


def submit_ids(seq: IdSeq, *, operation_id: OpaqueId | None = None) -> SubmitIds:
    return SubmitIds(
        operation_id=operation_id if operation_id is not None else seq.next(),
        created_audit_event_id=seq.next(),
        policy_decision_id=seq.next(),
        policy_audit_event_id=seq.next(),
        policy_transition_audit_event_id=seq.next(),
        allow_outbox_event_id=seq.next(),
        approval_id=seq.next(),
        approval_audit_event_id=seq.next(),
    )


def execute_ids(seq: IdSeq) -> ExecuteIds:
    return ExecuteIds(
        attempt_id=seq.next(),
        claim_transition_audit_event_id=seq.next(),
        attempt_audit_event_id=seq.next(),
        evidence_audit_event_id=seq.next(),
        execution_transition_audit_event_id=seq.next(),
        execution_outbox_event_id=seq.next(),
        verification_id=seq.next(),
        verification_audit_event_id=seq.next(),
    )


def recover_ids(seq: IdSeq) -> RecoverIds:
    return RecoverIds(
        evidence_audit_event_id=seq.next(),
        execution_transition_audit_event_id=seq.next(),
        execution_outbox_event_id=seq.next(),
        verification_id=seq.next(),
        verification_audit_event_id=seq.next(),
    )
