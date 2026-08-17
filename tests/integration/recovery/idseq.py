from __future__ import annotations

from stateback.domain.ids import OpaqueId
from stateback.recovery.ids import RecoveryIds
from stateback.runtime.ids import ExecuteIds, RecoverIds, SubmitIds
from tests.integration.runtime.idseq import (
    IdSeq,
    execute_ids,
    recover_ids,
    submit_ids,
)


def recovery_ids(seq: IdSeq) -> RecoveryIds:
    return RecoveryIds(
        verification_id=seq.next(),
        verification_start_audit_event_id=seq.next(),
        verification_complete_audit_event_id=seq.next(),
        start_transition_audit_event_id=seq.next(),
        start_outbox_event_id=seq.next(),
        complete_transition_audit_event_id=seq.next(),
        retry_outbox_event_id=seq.next(),
        manual_audit_event_id=seq.next(),
        reconciliation_decision_id=seq.next(),
        reconciliation_audit_event_id=seq.next(),
        execution_recover=recover_ids(seq),
    )


class SeqRecoveryIds:
    def __init__(self, seq: IdSeq) -> None:
        self._seq = seq

    def for_operation(self, operation_id: OpaqueId) -> RecoveryIds:
        del operation_id
        return recovery_ids(self._seq)


__all__ = [
    "ExecuteIds",
    "IdSeq",
    "RecoverIds",
    "SeqRecoveryIds",
    "SubmitIds",
    "execute_ids",
    "recover_ids",
    "recovery_ids",
    "submit_ids",
]
