from __future__ import annotations

import pytest

from stateback.compensation.intent import compute_compensation_intent_digest
from stateback.domain.enums import ArgumentsMode, CompensationKind
from stateback.domain.jsonutil import json_from_plain
from tests.unit.domain.fixtures import OP_ID

pytestmark = pytest.mark.unit


def test_digest_stable_for_equivalent_arguments() -> None:
    first = compute_compensation_intent_digest(
        original_operation_id=OP_ID,
        kind=CompensationKind.EXACT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"a": 1, "b": 2}),
        arguments_ref=None,
    )
    second = compute_compensation_intent_digest(
        original_operation_id=OP_ID,
        kind=CompensationKind.EXACT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"b": 2, "a": 1}),
        arguments_ref=None,
    )
    assert first == second


def test_digest_changes_with_kind() -> None:
    exact = compute_compensation_intent_digest(
        original_operation_id=OP_ID,
        kind=CompensationKind.EXACT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"a": 1}),
        arguments_ref=None,
    )
    approximate = compute_compensation_intent_digest(
        original_operation_id=OP_ID,
        kind=CompensationKind.APPROXIMATE,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"a": 1}),
        arguments_ref=None,
    )
    assert exact != approximate
