from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, ErrorKind
from stateback.domain.ids import OpaqueId
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
)
from tests.unit.providers.fixtures import make_adapter, make_context, make_request

pytestmark = pytest.mark.unit

_SECOND_ATTEMPT = OpaqueId(value="00000000-0000-4000-8000-000000000022")


def test_same_key_same_resource_replays_applied_without_second_row() -> None:
    adapter, store, _ = make_adapter()
    first = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    second = adapter.execute(
        make_context(attempt_id=_SECOND_ATTEMPT),
        make_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert first.outcome is EffectOutcome.APPLIED
    assert second.outcome is EffectOutcome.APPLIED
    assert second.external_operation_id == first.external_operation_id
    assert len(store.all_resources()) == 1


def test_same_key_different_resource_is_conflict_not_applied() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY, "res-1"))
    evidence = adapter.execute(
        make_context(attempt_id=_SECOND_ATTEMPT),
        make_request(EFFECT_MUTATE_PROVIDER_KEY, "res-2"),
    )
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.PROVIDER_REJECTED
    assert evidence.error.code == "ref.duplicate.conflict"
    assert evidence.error.provider_http_status == 409
    assert len(store.all_resources()) == 1


def test_natural_same_resource_replays() -> None:
    adapter, store, _ = make_adapter()
    first = adapter.execute(make_context(), make_request(EFFECT_MUTATE_NATURAL))
    second = adapter.execute(
        make_context(attempt_id=_SECOND_ATTEMPT, effect_key=None),
        make_request(EFFECT_MUTATE_NATURAL),
    )
    assert first.outcome is EffectOutcome.APPLIED
    assert second.outcome is EffectOutcome.APPLIED
    assert len(store.all_resources()) == 1


def test_none_mode_second_execute_creates_additional_row() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(effect_key=None), make_request(EFFECT_MUTATE_NONE))
    adapter.execute(
        make_context(effect_key=None, attempt_id=_SECOND_ATTEMPT),
        make_request(EFFECT_MUTATE_NONE),
    )
    assert len(store.all_resources()) == 2


def test_provider_key_missing_on_mutate_provider_key_is_validation() -> None:
    adapter, store, _ = make_adapter()
    evidence = adapter.execute(
        make_context(effect_key=None),
        make_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.VALIDATION
    assert evidence.error.code == "ref.validation.provider_key_required"
    assert store.all_resources() == ()
