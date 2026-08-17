from __future__ import annotations

import pytest

from stateback.compensation.exceptions import StatebackCompensationError
from stateback.compensation.kinds import compensation_decision_to_kind
from stateback.domain.enums import (
    CompensationState,
    OperationState,
    ReconciliationAction,
)
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind

pytestmark = pytest.mark.unit


def _decision(action: ReconciliationAction) -> ReconciliationDecision:
    return ReconciliationDecision(action=action, reason_code="test_reason")


@pytest.mark.parametrize(
    ("action", "expected_kind"),
    [
        (ReconciliationAction.MARK_SUCCEEDED, TransitionKind.COMPENSATION_APPLIED),
        (ReconciliationAction.MARK_FAILED, TransitionKind.COMPENSATION_OUTCOME_FAILED),
        (
            ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY,
            CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION,
        ),
        (
            ReconciliationAction.REMAIN_UNKNOWN,
            TransitionKind.COMPENSATION_OUTCOME_UNKNOWN,
        ),
        (
            ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
            TransitionKind.COMPENSATION_ESCALATE,
        ),
    ],
)
def test_compensating_verifying_mapper(
    action: ReconciliationAction,
    expected_kind: TransitionKind | CompensationProgressKind,
) -> None:
    result = compensation_decision_to_kind(
        parent_state=OperationState.COMPENSATING,
        compensation_state=CompensationState.VERIFYING,
        decision=_decision(action),
    )
    assert result.kind is expected_kind
    assert result.reason_code == "test_reason"


@pytest.mark.parametrize(
    ("action", "expected_kind"),
    [
        (
            ReconciliationAction.MARK_SUCCEEDED,
            TransitionKind.COMPENSATION_UNKNOWN_APPLIED,
        ),
        (ReconciliationAction.MARK_FAILED, TransitionKind.COMPENSATION_UNKNOWN_FAILED),
        (
            ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY,
            TransitionKind.COMPENSATION_UNKNOWN_RETRY,
        ),
        (
            ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
            TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
        ),
    ],
)
def test_compensation_unknown_mapper(
    action: ReconciliationAction,
    expected_kind: TransitionKind,
) -> None:
    result = compensation_decision_to_kind(
        parent_state=OperationState.COMPENSATION_UNKNOWN,
        compensation_state=CompensationState.UNKNOWN,
        decision=_decision(action),
    )
    assert result.kind is expected_kind
    assert result.reason_code == "test_reason"


def test_compensation_unknown_remain_unknown_raises() -> None:
    with pytest.raises(StatebackCompensationError) as exc:
        compensation_decision_to_kind(
            parent_state=OperationState.COMPENSATION_UNKNOWN,
            compensation_state=CompensationState.UNKNOWN,
            decision=_decision(ReconciliationAction.REMAIN_UNKNOWN),
        )
    assert exc.value.reason_code == "remain_unknown_noop"


def test_unsupported_pair_raises() -> None:
    with pytest.raises(StatebackCompensationError) as exc:
        compensation_decision_to_kind(
            parent_state=OperationState.COMPENSATED,
            compensation_state=CompensationState.SUCCEEDED,
            decision=_decision(ReconciliationAction.MARK_SUCCEEDED),
        )
    assert exc.value.reason_code == "unsupported_state"
