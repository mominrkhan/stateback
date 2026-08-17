from __future__ import annotations

import pytest

from stateback.domain.enums import OperationState, ReconciliationAction
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.recovery.exceptions import StatebackRecoveryError
from stateback.recovery.kinds import decision_to_kind
from stateback.transitions.kinds import TransitionKind

pytestmark = pytest.mark.unit


def _decision(action: ReconciliationAction) -> ReconciliationDecision:
    return ReconciliationDecision(action=action, reason_code=action.value.lower())


def test_verifying_maps_all_five_actions() -> None:
    mapping = {
        ReconciliationAction.MARK_SUCCEEDED: TransitionKind.VERIFICATION_APPLIED,
        ReconciliationAction.MARK_FAILED: TransitionKind.VERIFICATION_NOT_APPLIED_FAIL,
        ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: (
            TransitionKind.VERIFICATION_NOT_APPLIED_RETRY
        ),
        ReconciliationAction.REMAIN_UNKNOWN: TransitionKind.VERIFICATION_INCONCLUSIVE,
        ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: (
            TransitionKind.VERIFICATION_ESCALATE
        ),
    }
    for action, kind in mapping.items():
        decision = _decision(action)
        mapped = decision_to_kind(state=OperationState.VERIFYING, decision=decision)
        assert mapped.kind is kind
        assert mapped.reason_code == decision.reason_code


def test_unknown_maps_reconcile_and_escalate_kinds() -> None:
    mapping = {
        ReconciliationAction.MARK_SUCCEEDED: TransitionKind.UNKNOWN_RECONCILE_APPLIED,
        ReconciliationAction.MARK_FAILED: TransitionKind.UNKNOWN_RECONCILE_NOT_APPLIED,
        ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: TransitionKind.UNKNOWN_SAFE_RETRY,
        ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: TransitionKind.UNKNOWN_ESCALATE,
    }
    for action, kind in mapping.items():
        decision = _decision(action)
        mapped = decision_to_kind(state=OperationState.UNKNOWN, decision=decision)
        assert mapped.kind is kind
        assert mapped.reason_code == decision.reason_code


def test_unknown_remain_unknown_raises_remain_unknown_noop() -> None:
    decision = _decision(ReconciliationAction.REMAIN_UNKNOWN)
    with pytest.raises(StatebackRecoveryError) as exc:
        decision_to_kind(state=OperationState.UNKNOWN, decision=decision)
    assert exc.value.reason_code == "remain_unknown_noop"


def test_ready_state_raises_unsupported_state() -> None:
    decision = _decision(ReconciliationAction.MARK_SUCCEEDED)
    with pytest.raises(StatebackRecoveryError) as exc:
        decision_to_kind(state=OperationState.READY, decision=decision)
    assert exc.value.reason_code == "unsupported_state"
