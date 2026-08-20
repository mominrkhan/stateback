from __future__ import annotations

import pytest

from stateback.application.input_validation import (
    MAX_METADATA_ENTRIES,
    bounded_json_from_plain,
    validate_metadata,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_to_plain

pytestmark = pytest.mark.unit


def test_bounded_json_accepts_normal_canonical_input() -> None:
    converted = bounded_json_from_plain({"name": "demo", "values": [1, True]})
    assert json_to_plain(converted) == {"name": "demo", "values": [1, True]}


def test_bounded_json_rejects_excessive_nodes() -> None:
    with pytest.raises(ContractValidationError, match="supported length"):
        bounded_json_from_plain([None] * 1_001)


def test_metadata_limits_fail_before_persistence() -> None:
    with pytest.raises(ContractValidationError, match="entry count"):
        validate_metadata(
            tuple(
                (f"key-{index}", "value") for index in range(MAX_METADATA_ENTRIES + 1)
            )
        )
    with pytest.raises(ContractValidationError, match="field length"):
        validate_metadata((("key", "x" * 1_001),))
