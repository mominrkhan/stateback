"""Map ReconciliationDecision to a TransitionKind. Automatic recover always uses VERIFYING."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import OperationState, ReconciliationAction
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.recovery.exceptions import StatebackRecoveryError
from stateback.transitions.kinds import TransitionKind


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryKindDecision:
    kind: TransitionKind
    reason_code: str


_VERIFYING_ACTIONS: dict[ReconciliationAction, TransitionKind] = {
    ReconciliationAction.MARK_SUCCEEDED: TransitionKind.VERIFICATION_APPLIED,
    ReconciliationAction.MARK_FAILED: TransitionKind.VERIFICATION_NOT_APPLIED_FAIL,
    ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: (
        TransitionKind.VERIFICATION_NOT_APPLIED_RETRY
    ),
    ReconciliationAction.REMAIN_UNKNOWN: TransitionKind.VERIFICATION_INCONCLUSIVE,
    ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: TransitionKind.VERIFICATION_ESCALATE,
}

_UNKNOWN_ACTIONS: dict[ReconciliationAction, TransitionKind] = {
    ReconciliationAction.MARK_SUCCEEDED: TransitionKind.UNKNOWN_RECONCILE_APPLIED,
    ReconciliationAction.MARK_FAILED: TransitionKind.UNKNOWN_RECONCILE_NOT_APPLIED,
    ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: TransitionKind.UNKNOWN_SAFE_RETRY,
    ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: TransitionKind.UNKNOWN_ESCALATE,
}


def decision_to_kind(
    *,
    state: OperationState,
    decision: ReconciliationDecision,
) -> RecoveryKindDecision:
    if state is OperationState.VERIFYING:
        kind = _VERIFYING_ACTIONS[decision.action]
        return RecoveryKindDecision(kind=kind, reason_code=decision.reason_code)
    if state is OperationState.UNKNOWN:
        if decision.action is ReconciliationAction.REMAIN_UNKNOWN:
            raise StatebackRecoveryError(
                "remain_unknown_noop",
                "UNKNOWN + REMAIN_UNKNOWN has no transition",
            )
        kind = _UNKNOWN_ACTIONS[decision.action]
        return RecoveryKindDecision(kind=kind, reason_code=decision.reason_code)
    raise StatebackRecoveryError(
        "unsupported_state",
        f"decision_to_kind does not support state {state.value}",
    )
