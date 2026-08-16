from __future__ import annotations

import pytest

from stateback.domain.capability import ValidationResult
from stateback.domain.enums import EffectOutcome
from stateback.providers.protocol import ProviderAdapter
from stateback.providers.reference.effects import REFERENCE_PROVIDER
from tests.unit.providers.fixtures import make_adapter

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_protocol_is_runtime_checkable_on_reference_adapter() -> None:
    adapter, _, _ = make_adapter()
    assert isinstance(adapter, ProviderAdapter)


def test_effect_outcome_symbols_unchanged() -> None:
    values = {member.value for member in EffectOutcome}
    assert values == {"APPLIED", "NOT_APPLIED", "UNKNOWN"}


def test_reference_provider_name_is_stateback_reference() -> None:
    assert REFERENCE_PROVIDER == "stateback.reference"


def test_validation_result_wire_round_trip() -> None:
    original = ValidationResult(accepted=True, error=None)
    restored = ValidationResult.from_wire(original.to_wire())
    assert restored == original
