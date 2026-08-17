"""Stable IDs derived from a durable outbox identity.

Redelivery of one message reuses every transition/attempt identity. A new
outbox event produces a new namespace, so a later legal retry remains a new
durable attempt.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from stateback.compensation.ids import (
    CompensationIds,
    CompensationRetryIdFactory,
    CompensationRetryIds,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import WorkMessageV1
from stateback.recovery.ids import RecoveryIds
from stateback.runtime.ids import ExecuteIds, RecoverIds


def _id(namespace: str, role: str) -> OpaqueId:
    return OpaqueId(value=str(uuid5(NAMESPACE_URL, f"stateback:{namespace}:{role}")))


class _RetryIds(CompensationRetryIdFactory):
    def __init__(self, namespace: str) -> None:
        self._namespace = namespace

    def for_attempt(
        self, compensation_id: OpaqueId, attempt_number: int
    ) -> CompensationRetryIds:
        if attempt_number < 2:
            raise ValueError("retry attempt_number must be >= 2")
        prefix = f"retry:{compensation_id}:{attempt_number}"

        def make(role: str) -> OpaqueId:
            return _id(self._namespace, f"{prefix}:{role}")

        return CompensationRetryIds(
            parent_retry_transition_audit_event_id=make("parent-transition"),
            parent_retry_outbox_event_id=make("parent-outbox"),
            attempt_id=make("attempt"),
            attempt_audit_event_id=make("attempt-audit"),
            attempt_outbox_event_id=make("attempt-outbox"),
            resume_verification_id=make("resume-verification"),
            resume_verification_start_audit_event_id=make("resume-verify-start"),
            resume_verification_complete_audit_event_id=make("resume-verify-complete"),
            resume_verification_outbox_event_id=make("resume-verify-outbox"),
            resume_complete_transition_audit_event_id=make("resume-transition"),
            resume_complete_outbox_event_id=make("resume-outbox"),
            evidence_audit_event_id=make("evidence"),
            complete_transition_audit_event_id=make("complete-transition"),
            complete_outbox_event_id=make("complete-outbox"),
            verification_id=make("verification"),
            verification_start_audit_event_id=make("verify-start"),
            verification_complete_audit_event_id=make("verify-complete"),
            verification_outbox_event_id=make("verify-outbox"),
        )


class DeterministicWorkIds:
    def __init__(self, message: WorkMessageV1) -> None:
        self._namespace = message.outbox_event_id.value

    def _make(self, role: str) -> OpaqueId:
        return _id(self._namespace, role)

    def execute(self) -> ExecuteIds:
        return ExecuteIds(
            attempt_id=self._make("execute:attempt"),
            claim_transition_audit_event_id=self._make("execute:claim"),
            attempt_audit_event_id=self._make("execute:attempt-audit"),
            evidence_audit_event_id=self._make("execute:evidence"),
            execution_transition_audit_event_id=self._make("execute:transition"),
            execution_outbox_event_id=self._make("execute:outbox"),
            verification_id=self._make("execute:verification"),
            verification_audit_event_id=self._make("execute:verification-audit"),
        )

    def runtime_recover(self) -> RecoverIds:
        return RecoverIds(
            evidence_audit_event_id=self._make("runtime-recover:evidence"),
            execution_transition_audit_event_id=self._make(
                "runtime-recover:transition"
            ),
            execution_outbox_event_id=self._make("runtime-recover:outbox"),
            verification_id=self._make("runtime-recover:verification"),
            verification_audit_event_id=self._make(
                "runtime-recover:verification-audit"
            ),
        )

    def recovery(self) -> RecoveryIds:
        return RecoveryIds(
            verification_id=self._make("recovery:verification"),
            verification_start_audit_event_id=self._make("recovery:verify-start"),
            verification_complete_audit_event_id=self._make("recovery:verify-complete"),
            start_transition_audit_event_id=self._make("recovery:start-transition"),
            start_outbox_event_id=self._make("recovery:start-outbox"),
            complete_transition_audit_event_id=self._make(
                "recovery:complete-transition"
            ),
            retry_outbox_event_id=self._make("recovery:retry-outbox"),
            manual_audit_event_id=self._make("recovery:manual-audit"),
            reconciliation_decision_id=self._make("recovery:reconciliation"),
            reconciliation_audit_event_id=self._make("recovery:reconciliation-audit"),
            execution_recover=self.runtime_recover(),
        )

    def compensation(self) -> CompensationIds:
        return CompensationIds(
            compensation_id=self._make("compensation:id"),
            compensation_attempt_id=self._make("compensation:attempt"),
            start_transition_audit_event_id=self._make("compensation:start-transition"),
            compensation_requested_audit_event_id=self._make(
                "compensation:requested-audit"
            ),
            start_outbox_event_id=self._make("compensation:start-outbox"),
            claim_attempt_audit_event_id=self._make("compensation:claim-audit"),
            evidence_audit_event_id=self._make("compensation:evidence"),
            complete_transition_audit_event_id=self._make(
                "compensation:complete-transition"
            ),
            complete_outbox_event_id=self._make("compensation:complete-outbox"),
            verification_id=self._make("compensation:verification"),
            verification_start_audit_event_id=self._make("compensation:verify-start"),
            verification_complete_audit_event_id=self._make(
                "compensation:verify-complete"
            ),
            verification_outbox_event_id=self._make("compensation:verify-outbox"),
            manual_audit_event_id=self._make("compensation:manual-audit"),
            operator_audit_event_id=self._make("compensation:operator-audit"),
            retry_ids_for=_RetryIds(self._namespace),
        )
