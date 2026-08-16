"""Approval binding checks — `contracts/POLICY_CONTRACT.md` §7.

Authorization of the approver is not decided here (Phase 9).
"""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    ApprovalBindingVerdict,
    ApprovalState,
    OperationState,
)
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval
from stateback.domain.time import UtcTimestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalBindingDecision:
    verdict: ApprovalBindingVerdict
    reason_code: str


def evaluate_approval_binding(
    *,
    approval: Approval,
    operation: Operation,
    now: UtcTimestamp,
) -> ApprovalBindingDecision:
    if approval.operation_id != operation.operation_id:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="operation_id_mismatch",
        )
    if approval.intent_digest != operation.intent.intent_digest:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="intent_digest_mismatch",
        )
    if approval.operation_version != operation.version:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="operation_version_mismatch",
        )
    if operation.current_policy_decision_id is None:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="missing_current_policy_decision",
        )
    if approval.policy_decision_id != operation.current_policy_decision_id:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="policy_decision_mismatch",
        )
    if approval.state is not ApprovalState.APPROVED:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="approval_not_approved",
        )
    if operation.state is not OperationState.AWAITING_APPROVAL:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="operation_not_awaiting_approval",
        )
    if approval.expires_at is not None and now.value >= approval.expires_at.value:
        return ApprovalBindingDecision(
            verdict=ApprovalBindingVerdict.INVALID,
            reason_code="approval_expired",
        )
    return ApprovalBindingDecision(
        verdict=ApprovalBindingVerdict.VALID,
        reason_code="bound_to_current_intent",
    )
