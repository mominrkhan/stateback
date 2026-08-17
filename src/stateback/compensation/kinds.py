"""Decision → transition/progress kind for compensation recovery. Pure. No I/O."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.compensation.exceptions import StatebackCompensationError
from stateback.domain.enums import (
    CompensationState,
    OperationState,
    ReconciliationAction,
)
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind

_COMPENSATING_VERIFYING: dict[
    ReconciliationAction, TransitionKind | CompensationProgressKind
] = {
    ReconciliationAction.MARK_SUCCEEDED: TransitionKind.COMPENSATION_APPLIED,
    ReconciliationAction.MARK_FAILED: TransitionKind.COMPENSATION_OUTCOME_FAILED,
    ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: (
        CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION
    ),
    ReconciliationAction.REMAIN_UNKNOWN: TransitionKind.COMPENSATION_OUTCOME_UNKNOWN,
    ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: TransitionKind.COMPENSATION_ESCALATE,
}

_COMPENSATION_UNKNOWN: dict[ReconciliationAction, TransitionKind] = {
    ReconciliationAction.MARK_SUCCEEDED: TransitionKind.COMPENSATION_UNKNOWN_APPLIED,
    ReconciliationAction.MARK_FAILED: TransitionKind.COMPENSATION_UNKNOWN_FAILED,
    ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: (
        TransitionKind.COMPENSATION_UNKNOWN_RETRY
    ),
    ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: (
        TransitionKind.COMPENSATION_UNKNOWN_ESCALATE
    ),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class CompensationKindDecision:
    kind: TransitionKind | CompensationProgressKind
    reason_code: str


def compensation_decision_to_kind(
    *,
    parent_state: OperationState,
    compensation_state: CompensationState,
    decision: ReconciliationDecision,
) -> CompensationKindDecision:
    if (
        parent_state is OperationState.COMPENSATING
        and compensation_state is CompensationState.VERIFYING
    ):
        kind = _COMPENSATING_VERIFYING.get(decision.action)
        if kind is not None:
            return CompensationKindDecision(kind=kind, reason_code=decision.reason_code)
    if (
        parent_state is OperationState.COMPENSATION_UNKNOWN
        and compensation_state is CompensationState.UNKNOWN
    ):
        if decision.action is ReconciliationAction.REMAIN_UNKNOWN:
            raise StatebackCompensationError(
                "remain_unknown_noop", "compensation recovery is a no-op"
            )
        kind = _COMPENSATION_UNKNOWN.get(decision.action)
        if kind is not None:
            return CompensationKindDecision(kind=kind, reason_code=decision.reason_code)
    raise StatebackCompensationError(
        "unsupported_state",
        f"unsupported (parent={parent_state}, compensation={compensation_state}) pair",
    )
