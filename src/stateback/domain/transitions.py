"""Legal transition tables from `STATE_MACHINES.md`.

This module answers whether a from→to pair is listed. It does not apply
transitions, persist them, or evaluate policy/approval/evidence preconditions.
Those belong to Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.compensation import PARENT_FOR_COMPENSATION_STATE
from stateback.domain.enums import (
    ApprovalState,
    CompensationState,
    OperationState,
    OutboxState,
    TransitionVerdict,
)

LEGAL_OPERATION_TRANSITIONS: frozenset[tuple[OperationState | None, OperationState]] = (
    frozenset(
        {
            (None, OperationState.PENDING_POLICY),
            (OperationState.PENDING_POLICY, OperationState.READY),
            (OperationState.PENDING_POLICY, OperationState.AWAITING_APPROVAL),
            (OperationState.PENDING_POLICY, OperationState.DENIED),
            (OperationState.PENDING_POLICY, OperationState.CANCELLED),
            (OperationState.AWAITING_APPROVAL, OperationState.READY),
            (OperationState.AWAITING_APPROVAL, OperationState.DENIED),
            (OperationState.AWAITING_APPROVAL, OperationState.CANCELLED),
            (OperationState.READY, OperationState.EXECUTING),
            (OperationState.READY, OperationState.CANCELLED),
            (OperationState.EXECUTING, OperationState.SUCCEEDED),
            (OperationState.EXECUTING, OperationState.VERIFYING),
            (OperationState.EXECUTING, OperationState.READY),
            (OperationState.EXECUTING, OperationState.FAILED),
            (OperationState.EXECUTING, OperationState.UNKNOWN),
            (OperationState.VERIFYING, OperationState.SUCCEEDED),
            (OperationState.VERIFYING, OperationState.READY),
            (OperationState.VERIFYING, OperationState.FAILED),
            (OperationState.VERIFYING, OperationState.UNKNOWN),
            (OperationState.VERIFYING, OperationState.MANUAL_INTERVENTION),
            (OperationState.UNKNOWN, OperationState.VERIFYING),
            (OperationState.UNKNOWN, OperationState.READY),
            (OperationState.UNKNOWN, OperationState.SUCCEEDED),
            (OperationState.UNKNOWN, OperationState.FAILED),
            (OperationState.UNKNOWN, OperationState.MANUAL_INTERVENTION),
            (OperationState.SUCCEEDED, OperationState.COMPENSATING),
            (OperationState.FAILED, OperationState.COMPENSATING),
            (OperationState.MANUAL_INTERVENTION, OperationState.VERIFYING),
            (OperationState.MANUAL_INTERVENTION, OperationState.COMPENSATING),
            (OperationState.MANUAL_INTERVENTION, OperationState.READY),
            (OperationState.COMPENSATING, OperationState.COMPENSATED),
            (OperationState.COMPENSATING, OperationState.COMPENSATION_UNKNOWN),
            (OperationState.COMPENSATING, OperationState.COMPENSATION_FAILED),
            (OperationState.COMPENSATING, OperationState.MANUAL_INTERVENTION),
            (OperationState.COMPENSATION_UNKNOWN, OperationState.COMPENSATING),
            (OperationState.COMPENSATION_UNKNOWN, OperationState.COMPENSATED),
            (OperationState.COMPENSATION_UNKNOWN, OperationState.COMPENSATION_FAILED),
            (OperationState.COMPENSATION_UNKNOWN, OperationState.MANUAL_INTERVENTION),
            (OperationState.COMPENSATION_FAILED, OperationState.COMPENSATING),
            (OperationState.COMPENSATION_FAILED, OperationState.MANUAL_INTERVENTION),
        }
    )
)

LEGAL_COMPENSATION_TRANSITIONS: frozenset[
    tuple[CompensationState, CompensationState]
] = frozenset(
    {
        (CompensationState.PENDING, CompensationState.EXECUTING),
        (CompensationState.EXECUTING, CompensationState.SUCCEEDED),
        (CompensationState.EXECUTING, CompensationState.VERIFYING),
        (CompensationState.EXECUTING, CompensationState.UNKNOWN),
        (CompensationState.EXECUTING, CompensationState.FAILED),
        (CompensationState.VERIFYING, CompensationState.SUCCEEDED),
        (CompensationState.VERIFYING, CompensationState.EXECUTING),
        (CompensationState.VERIFYING, CompensationState.UNKNOWN),
        (CompensationState.VERIFYING, CompensationState.FAILED),
        (CompensationState.UNKNOWN, CompensationState.VERIFYING),
        (CompensationState.UNKNOWN, CompensationState.EXECUTING),
        (CompensationState.UNKNOWN, CompensationState.SUCCEEDED),
        (CompensationState.UNKNOWN, CompensationState.FAILED),
        (CompensationState.FAILED, CompensationState.EXECUTING),
    }
)

LEGAL_APPROVAL_TRANSITIONS: frozenset[tuple[ApprovalState, ApprovalState]] = frozenset(
    {
        (ApprovalState.PENDING, ApprovalState.APPROVED),
        (ApprovalState.PENDING, ApprovalState.REJECTED),
        (ApprovalState.PENDING, ApprovalState.EXPIRED),
        (ApprovalState.PENDING, ApprovalState.CANCELLED),
    }
)

LEGAL_OUTBOX_TRANSITIONS: frozenset[tuple[OutboxState, OutboxState]] = frozenset(
    {
        (OutboxState.PENDING, OutboxState.PUBLISHED),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionDecision:
    verdict: TransitionVerdict
    from_state: str | None
    to_state: str
    reason_code: str

    def is_legal(self) -> bool:
        return self.verdict is TransitionVerdict.LEGAL


def evaluate_operation_transition(
    from_state: OperationState | None,
    to_state: OperationState,
) -> TransitionDecision:
    if (from_state, to_state) in LEGAL_OPERATION_TRANSITIONS:
        return TransitionDecision(
            verdict=TransitionVerdict.LEGAL,
            from_state=None if from_state is None else from_state.value,
            to_state=to_state.value,
            reason_code="listed_in_state_machines",
        )
    return TransitionDecision(
        verdict=TransitionVerdict.ILLEGAL,
        from_state=None if from_state is None else from_state.value,
        to_state=to_state.value,
        reason_code="unlisted_operation_transition",
    )


def evaluate_compensation_transition(
    from_state: CompensationState,
    to_state: CompensationState,
) -> TransitionDecision:
    if (from_state, to_state) in LEGAL_COMPENSATION_TRANSITIONS:
        return TransitionDecision(
            verdict=TransitionVerdict.LEGAL,
            from_state=from_state.value,
            to_state=to_state.value,
            reason_code="listed_in_state_machines",
        )
    return TransitionDecision(
        verdict=TransitionVerdict.ILLEGAL,
        from_state=from_state.value,
        to_state=to_state.value,
        reason_code="unlisted_compensation_transition",
    )


def evaluate_approval_transition(
    from_state: ApprovalState,
    to_state: ApprovalState,
) -> TransitionDecision:
    if (from_state, to_state) in LEGAL_APPROVAL_TRANSITIONS:
        return TransitionDecision(
            verdict=TransitionVerdict.LEGAL,
            from_state=from_state.value,
            to_state=to_state.value,
            reason_code="listed_in_state_machines",
        )
    return TransitionDecision(
        verdict=TransitionVerdict.ILLEGAL,
        from_state=from_state.value,
        to_state=to_state.value,
        reason_code="unlisted_approval_transition",
    )


def evaluate_outbox_transition(
    from_state: OutboxState,
    to_state: OutboxState,
) -> TransitionDecision:
    if (from_state, to_state) in LEGAL_OUTBOX_TRANSITIONS:
        return TransitionDecision(
            verdict=TransitionVerdict.LEGAL,
            from_state=from_state.value,
            to_state=to_state.value,
            reason_code="listed_in_state_machines",
        )
    return TransitionDecision(
        verdict=TransitionVerdict.ILLEGAL,
        from_state=from_state.value,
        to_state=to_state.value,
        reason_code="unlisted_outbox_transition",
    )


def compensation_parent_is_consistent(
    compensation_state: CompensationState,
    parent_state: OperationState,
) -> TransitionDecision:
    expected = PARENT_FOR_COMPENSATION_STATE[compensation_state]
    if parent_state is expected:
        return TransitionDecision(
            verdict=TransitionVerdict.LEGAL,
            from_state=compensation_state.value,
            to_state=parent_state.value,
            reason_code="compensation_parent_consistent",
        )
    return TransitionDecision(
        verdict=TransitionVerdict.ILLEGAL,
        from_state=compensation_state.value,
        to_state=parent_state.value,
        reason_code="compensation_parent_inconsistent",
    )
