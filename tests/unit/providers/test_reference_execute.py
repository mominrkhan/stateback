from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from stateback.domain.enums import EffectOutcome, ErrorKind
from stateback.domain.jsonutil import JsonObject
from stateback.domain.time import UtcTimestamp
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_READ_RESOURCE,
)
from stateback.providers.reference.scripts import ReferenceExecuteScript
from tests.unit.providers.fixtures import make_adapter, make_context, make_request

pytestmark = pytest.mark.unit

_ADAPTER_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "stateback"
    / "providers"
    / "reference"
    / "adapter.py"
)


def test_applied_returns_external_ids() -> None:
    adapter, store, _ = make_adapter()
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.APPLIED
    assert evidence.error is None
    assert evidence.external_operation_id is not None
    assert evidence.external_resource_ids == ("res-1",)
    assert len(store.all_resources()) == 1


def test_timeout_after_send_is_unknown_and_store_has_resource() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.TRANSIENT_TRANSPORT
    assert evidence.error.code == "ref.timeout.after_send"
    assert evidence.external_operation_id is None
    assert len(store.all_resources()) == 1


def test_applied_response_lost_omits_ids_but_store_has_them() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.external_operation_id is None
    assert evidence.external_resource_ids == ()
    row = store.all_resources()[0]
    assert row.external_operation_id.startswith("refop:")
    assert row.resource_id == "res-1"


def test_rejected_before_accept_does_not_write_store() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.code == "ref.rejected.before_accept"
    assert store.all_resources() == ()


def test_unavailable_no_accept_is_not_applied() -> None:
    adapter, _, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_UNAVAILABLE)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.PROVIDER_UNAVAILABLE
    assert evidence.error.retryable_infrastructure is True


def test_malformed_after_accept_is_unknown_and_writes() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_MALFORMED)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE
    assert len(store.all_resources()) == 1


def test_deadline_before_send_is_not_applied() -> None:
    adapter, store, _ = make_adapter()
    past = UtcTimestamp(value=datetime(2026, 8, 16, 21, 0, 0, tzinfo=UTC))
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED)
    evidence = adapter.execute(
        make_context(deadline=past),
        make_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.code == "ref.deadline.not_sent"
    assert store.all_resources() == ()


def test_read_resource_success_is_not_applied() -> None:
    adapter, store, _ = make_adapter()
    evidence = adapter.execute(make_context(), make_request(EFFECT_READ_RESOURCE))
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is None
    assert store.all_resources() == ()
    assert evidence.evidence is not None
    fields = evidence.evidence.evidence_fields
    assert isinstance(fields, JsonObject)
    assert fields.as_dict()["present"] == "false"


def test_execute_does_not_call_transition_service() -> None:
    adapter, _, _ = make_adapter()
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    source = _ADAPTER_PATH.read_text(encoding="utf-8")
    assert "stateback.transitions" not in source


def test_providers_module_does_not_import_transitions() -> None:
    source = _ADAPTER_PATH.read_text(encoding="utf-8")
    assert "stateback.transitions" not in source
    assert "update_cas" not in source
    assert "TransitionService" not in source
