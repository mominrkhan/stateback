from __future__ import annotations

import pytest

from stateback.domain.canonical import sha256_hex
from stateback.domain.enums import ArgumentsMode
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import (
    compute_canonical_arguments_hash,
    compute_intent_digest,
)
from stateback.domain.jsonutil import json_from_plain
from tests.unit.domain.fixtures import EFFECT, REQUESTER

pytestmark = pytest.mark.unit


def test_float_rejected() -> None:
    with pytest.raises(ContractValidationError) as exc:
        json_from_plain({"n": 1.5})
    assert exc.value.reason_code == "non_canonical_number"


def test_object_key_order_does_not_change_hash() -> None:
    left = json_from_plain({"b": 1, "a": 2})
    right = json_from_plain({"a": 2, "b": 1})
    assert sha256_hex(left) == sha256_hex(right)


def test_materially_different_arguments_change_hash() -> None:
    left = compute_canonical_arguments_hash(
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"name": "a"}),
        arguments_ref=None,
    )
    right = compute_canonical_arguments_hash(
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"name": "b"}),
        arguments_ref=None,
    )
    assert left != right


def test_intent_digest_stable_for_identical_material() -> None:
    args_hash = compute_canonical_arguments_hash(
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"name": "demo"}),
        arguments_ref=None,
    )
    left = compute_intent_digest(
        effect=EFFECT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments_ref=None,
        canonical_arguments_hash=args_hash,
        requester=REQUESTER,
        metadata=(("env", "dev"),),
    )
    right = compute_intent_digest(
        effect=EFFECT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments_ref=None,
        canonical_arguments_hash=args_hash,
        requester=REQUESTER,
        metadata=(("env", "dev"),),
    )
    assert left == right
    assert len(left) == 64
