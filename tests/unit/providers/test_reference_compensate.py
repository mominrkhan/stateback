from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, ErrorKind
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_MITIGATING,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
)
from stateback.providers.reference.scripts import ReferenceCompensateScript
from tests.unit.providers.fixtures import (
    make_adapter,
    make_compensate_request,
    make_context,
    make_request,
)

pytestmark = pytest.mark.unit


def test_exact_compensate_marks_compensated_and_keeps_original_row() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    evidence = adapter.compensate(make_context(), make_compensate_request())
    assert evidence.outcome is EffectOutcome.APPLIED
    rows = store.all_resources()
    assert len(rows) == 1
    assert rows[0].applied is True
    assert rows[0].compensated is True
    assert rows[0].mitigated is False


def test_mitigating_sets_mitigated_not_compensated() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_MITIGATING))
    evidence = adapter.compensate(make_context(), make_compensate_request())
    assert evidence.outcome is EffectOutcome.APPLIED
    row = store.all_resources()[0]
    assert row.mitigated is True
    assert row.compensated is False
    assert row.applied is True


def test_none_capability_compensate_not_applied_unsupported() -> None:
    adapter, _, _ = make_adapter()
    adapter.execute(make_context(effect_key=None), make_request(EFFECT_MUTATE_NONE))
    evidence = adapter.compensate(
        make_context(),
        make_compensate_request(provider_idempotency_key=None),
    )
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.UNSUPPORTED_CAPABILITY
    assert evidence.error.code == "ref.unsupported.compensation"


def test_compensate_timeout_unknown_still_marks() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    adapter.enqueue_compensate(ReferenceCompensateScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    evidence = adapter.compensate(make_context(), make_compensate_request())
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.code == "ref.timeout.after_send"
    assert store.all_resources()[0].compensated is True


def test_compensate_does_not_delete_history() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    adapter.compensate(make_context(), make_compensate_request())
    rows = store.all_resources()
    assert len(rows) == 1
    assert rows[0].resource_id == "res-1"
    assert rows[0].applied is True


def test_compensate_replay_same_key_is_applied_once() -> None:
    adapter, store, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    first = adapter.compensate(make_context(), make_compensate_request())
    adapter.enqueue_compensate(ReferenceCompensateScript.NOT_APPLIED_REJECTED)
    second = adapter.compensate(make_context(), make_compensate_request())
    assert first.outcome is EffectOutcome.APPLIED
    assert second.outcome is EffectOutcome.APPLIED
    assert store.all_resources()[0].compensated is True
    assert len(store.all_resources()) == 1
