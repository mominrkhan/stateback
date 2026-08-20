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


def test_kind_count_is_42() -> None:
    assert len(KIND_TO_EDGE) == 42
    assert len(LEGAL_OPERATION_TRANSITIONS) == 42
    assert len(TransitionKind) == 42


def test_every_legal_pair_has_exactly_one_kind() -> None:
    pairs = list(KIND_TO_EDGE.values())
    assert len(pairs) == len(set(pairs))
    assert set(pairs) == set(LEGAL_OPERATION_TRANSITIONS)


def test_compensation_progress_kind_not_in_operation_edges() -> None:
    assert CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION.value not in {
        kind.value for kind in TransitionKind
    }
    assert "CLAIM_COMPENSATION_EXECUTION" not in {kind.value for kind in KIND_TO_EDGE}


def test_compensation_progress_kind_count_is_4() -> None:
    assert len(CompensationProgressKind) == 4


def test_new_progress_kinds_not_in_kind_to_edge() -> None:
    progress_values = {kind.value for kind in CompensationProgressKind}
    edge_values = {kind.value for kind in KIND_TO_EDGE}
    assert progress_values.isdisjoint(edge_values)
    assert progress_values.isdisjoint({kind.value for kind in TransitionKind})
