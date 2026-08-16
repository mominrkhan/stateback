from __future__ import annotations

import asyncio

import pytest

from stateback.domain.enums import EffectOutcome, ErrorKind
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonObject
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import ReferenceExecuteScript
from tests.unit.providers.fixtures import make_adapter, make_context, make_request

pytestmark = pytest.mark.unit

_SECOND_ATTEMPT = OpaqueId(value="00000000-0000-4000-8000-000000000032")


def test_auth_script_is_not_applied_authentication() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_AUTH)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.AUTHENTICATION
    assert evidence.error.code == "ref.auth.missing"
    assert evidence.error.message == "provider authentication failed"
    assert store.all_resources() == ()


def test_rate_limit_not_accepted_is_not_applied() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_RATE_LIMIT)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.RATE_LIMITED
    assert evidence.error.code == "ref.rate_limited.not_accepted"
    assert evidence.error.retryable_infrastructure is True
    assert store.all_resources() == ()


def test_rate_limit_ambiguous_is_unknown_and_writes() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_RATE_LIMIT_AMBIGUOUS)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.RATE_LIMITED
    assert evidence.error.code == "ref.rate_limited.ambiguous"
    assert evidence.error.retryable_infrastructure is True
    assert len(store.all_resources()) == 1


def test_retryable_infrastructure_does_not_reinvoke_execute() -> None:
    adapter, store, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED)
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    adapter.execute(
        make_context(effect_key="key-2", attempt_id=_SECOND_ATTEMPT),
        make_request(EFFECT_MUTATE_PROVIDER_KEY, "res-2"),
    )
    assert len(store.all_resources()) == 2
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    adapter.execute(
        make_context(
            effect_key="key-3",
            attempt_id=OpaqueId(value="00000000-0000-4000-8000-000000000033"),
        ),
        make_request(EFFECT_MUTATE_PROVIDER_KEY, "res-3"),
    )
    assert adapter._execute_scripts == []


def test_unclassified_exception_becomes_unknown_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, store, _ = make_adapter()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "put", _boom)
    evidence = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.INTERNAL
    assert evidence.error.code == "ref.internal.unclassified"
    assert evidence.error.message == "unclassified adapter exception"
    assert "boom" not in evidence.error.message
    details = evidence.error.details
    assert isinstance(details, JsonObject)
    assert details.as_dict() == {"exception_type": "RuntimeError"}


def test_cancelled_error_is_not_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, store, _ = make_adapter()

    def _cancel(*_args: object, **_kwargs: object) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "put", _cancel)
    with pytest.raises(asyncio.CancelledError):
        adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
