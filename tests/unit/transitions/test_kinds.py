from __future__ import annotations

import pytest

from stateback.domain.transitions import LEGAL_OPERATION_TRANSITIONS
from stateback.transitions.kinds import (
    KIND_TO_EDGE,
    CompensationProgressKind,
    TransitionKind,
)

pytestmark = pytest.mark.unit


def test_kind_to_edge_matches_legal_operation_transitions() -> None:
    assert frozenset(KIND_TO_EDGE.values()) == LEGAL_OPERATION_TRANSITIONS


def test_kind_count_is_40() -> None:
    assert len(KIND_TO_EDGE) == 40
    assert len(LEGAL_OPERATION_TRANSITIONS) == 40
    assert len(TransitionKind) == 40


def test_every_legal_pair_has_exactly_one_kind() -> None:
    pairs = list(KIND_TO_EDGE.values())
    assert len(pairs) == len(set(pairs))
    assert set(pairs) == set(LEGAL_OPERATION_TRANSITIONS)


def test_compensation_progress_kind_not_in_operation_edges() -> None:
    assert CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION.value not in {
        kind.value for kind in TransitionKind
    }
    assert "CLAIM_COMPENSATION_EXECUTION" not in {kind.value for kind in KIND_TO_EDGE}
