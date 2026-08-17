"""Stable application-boundary identifiers derived from request identity."""

from __future__ import annotations

import uuid

from stateback.approval.commands import ApprovalDecisionIds
from stateback.compensation.ids import (
    CompensationIds,
    CompensationRetryIdFactory,
    CompensationRetryIds,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef
from stateback.recovery.ids import RecoveryIds
from stateback.runtime.ids import RecoverIds, SubmitIds

_NAMESPACE = uuid.UUID("93f5a0e9-7b29-5ed1-9ac3-3583b95e4036")


def _id(identity: str, purpose: str) -> OpaqueId:
    return OpaqueId(value=str(uuid.uuid5(_NAMESPACE, f"{identity}:{purpose}")))


def request_identity(principal: PrincipalRef, idempotency_key: str) -> str:
    return f"sb:v1:request:{principal.type.value}:{principal.id}:{idempotency_key}"


def submit_ids(identity: str) -> SubmitIds:
    return SubmitIds(
        operation_id=_id(identity, "operation"),
        created_audit_event_id=_id(identity, "operation-created-audit"),
        policy_decision_id=_id(identity, "policy-decision"),
        policy_audit_event_id=_id(identity, "policy-audit"),
        policy_transition_audit_event_id=_id(identity, "policy-transition-audit"),
        allow_outbox_event_id=_id(identity, "policy-allow-outbox"),
        approval_id=_id(identity, "approval"),
        approval_audit_event_id=_id(identity, "approval-audit"),
    )


def approval_ids(operation_id: OpaqueId, action_key: str) -> ApprovalDecisionIds:
    identity = f"sb:v1:approval:{operation_id}:{action_key}"
    return ApprovalDecisionIds(
        transition_audit_event_id=_id(identity, "transition-audit"),
        approval_audit_event_id=_id(identity, "decision-audit"),
        outbox_event_id=_id(identity, "outbox"),
    )


def recovery_ids(operation_id: OpaqueId, action_key: str) -> RecoveryIds:
    identity = f"sb:v1:recovery:{operation_id}:{action_key}"
    return RecoveryIds(
        verification_id=_id(identity, "verification"),
        verification_start_audit_event_id=_id(identity, "verification-start-audit"),
        verification_complete_audit_event_id=_id(
            identity, "verification-complete-audit"
        ),
        start_transition_audit_event_id=_id(identity, "start-transition-audit"),
        start_outbox_event_id=_id(identity, "start-outbox"),
        complete_transition_audit_event_id=_id(identity, "complete-transition-audit"),
        retry_outbox_event_id=_id(identity, "retry-outbox"),
        manual_audit_event_id=_id(identity, "manual-audit"),
        reconciliation_decision_id=_id(identity, "reconciliation-decision"),
        reconciliation_audit_event_id=_id(identity, "reconciliation-audit"),
        execution_recover=RecoverIds(
            evidence_audit_event_id=_id(identity, "execution-evidence-audit"),
            execution_transition_audit_event_id=_id(
                identity, "execution-transition-audit"
            ),
            execution_outbox_event_id=_id(identity, "execution-outbox"),
            verification_id=_id(identity, "execution-verification"),
            verification_audit_event_id=_id(identity, "execution-verification-audit"),
        ),
    )


class _RetryIds(CompensationRetryIdFactory):
    def __init__(self, identity: str) -> None:
        self._identity = identity

    def for_attempt(
        self, compensation_id: OpaqueId, attempt_number: int
    ) -> CompensationRetryIds:
        prefix = f"{self._identity}:{compensation_id}:{attempt_number}"
        names = (
            "parent_retry_transition_audit_event_id",
            "parent_retry_outbox_event_id",
            "attempt_id",
            "attempt_audit_event_id",
            "attempt_outbox_event_id",
            "resume_verification_id",
            "resume_verification_start_audit_event_id",
            "resume_verification_complete_audit_event_id",
            "resume_verification_outbox_event_id",
            "resume_complete_transition_audit_event_id",
            "resume_complete_outbox_event_id",
            "evidence_audit_event_id",
            "complete_transition_audit_event_id",
            "complete_outbox_event_id",
            "verification_id",
            "verification_start_audit_event_id",
            "verification_complete_audit_event_id",
            "verification_outbox_event_id",
        )
        return CompensationRetryIds(**{name: _id(prefix, name) for name in names})


def compensation_ids(operation_id: OpaqueId, action_key: str) -> CompensationIds:
    identity = f"sb:v1:compensation:{operation_id}:{action_key}"
    names = (
        "compensation_id",
        "compensation_attempt_id",
        "start_transition_audit_event_id",
        "compensation_requested_audit_event_id",
        "start_outbox_event_id",
        "claim_attempt_audit_event_id",
        "evidence_audit_event_id",
        "complete_transition_audit_event_id",
        "complete_outbox_event_id",
        "verification_id",
        "verification_start_audit_event_id",
        "verification_complete_audit_event_id",
        "verification_outbox_event_id",
        "manual_audit_event_id",
        "operator_audit_event_id",
    )
    return CompensationIds(
        **{name: _id(identity, name) for name in names},
        retry_ids_for=_RetryIds(identity),
    )
