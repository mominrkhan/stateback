from __future__ import annotations

import pytest

from stateback.domain.enums import (
    CompensationState,
    OperationState,
    TransitionVerdict,
)
from stateback.domain.transitions import (
    LEGAL_OPERATION_TRANSITIONS,
    compensation_parent_is_consistent,
    evaluate_operation_transition,
)

pytestmark = pytest.mark.unit

# Independent encoding of STATE_MACHINES.md §4. Do not derive this from
# LEGAL_OPERATION_TRANSITIONS — that would test the table against itself.
_CANONICAL_OPERATION_TRANSITIONS: frozenset[
    tuple[OperationState | None, OperationState]
] = frozenset(
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


def test_every_listed_operation_transition_is_legal() -> None:
    assert LEGAL_OPERATION_TRANSITIONS == _CANONICAL_OPERATION_TRANSITIONS
    for from_state, to_state in sorted(
        _CANONICAL_OPERATION_TRANSITIONS,
        key=lambda pair: (
            "" if pair[0] is None else pair[0].value,
            pair[1].value,
        ),
    ):
        decision = evaluate_operation_transition(from_state, to_state)
        assert decision.verdict is TransitionVerdict.LEGAL


def test_executing_failed_and_unknown_are_legal_and_distinct() -> None:
    failed = evaluate_operation_transition(
        OperationState.EXECUTING, OperationState.FAILED
    )
    unknown = evaluate_operation_transition(
        OperationState.EXECUTING, OperationState.UNKNOWN
    )
    assert failed.verdict is TransitionVerdict.LEGAL
    assert unknown.verdict is TransitionVerdict.LEGAL
    assert failed.to_state != unknown.to_state
    assert failed.to_state == OperationState.FAILED.value
    assert unknown.to_state == OperationState.UNKNOWN.value


def test_cancelled_after_executing_is_illegal() -> None:
    decision = evaluate_operation_transition(
        OperationState.EXECUTING, OperationState.CANCELLED
    )
    assert decision.verdict is TransitionVerdict.ILLEGAL
    assert decision.reason_code == "unlisted_operation_transition"


@pytest.mark.parametrize(
    ("comp", "parent", "legal"),
    [
        (CompensationState.PENDING, OperationState.COMPENSATING, True),
        (CompensationState.EXECUTING, OperationState.COMPENSATING, True),
        (CompensationState.VERIFYING, OperationState.COMPENSATING, True),
        (CompensationState.UNKNOWN, OperationState.COMPENSATION_UNKNOWN, True),
        (CompensationState.SUCCEEDED, OperationState.COMPENSATED, True),
        (CompensationState.FAILED, OperationState.COMPENSATION_FAILED, True),
        (CompensationState.SUCCEEDED, OperationState.SUCCEEDED, False),
    ],
)
def test_compensation_parent_consistency(
    comp: CompensationState, parent: OperationState, legal: bool
) -> None:
    decision = compensation_parent_is_consistent(comp, parent)
    if legal:
        assert decision.verdict is TransitionVerdict.LEGAL
    else:
        assert decision.verdict is TransitionVerdict.ILLEGAL
