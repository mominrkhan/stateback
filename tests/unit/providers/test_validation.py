from __future__ import annotations

import pytest

from stateback.domain.capability import ProviderExecutionRequest
from stateback.domain.enums import ErrorKind
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import ReferenceExecuteScript
from tests.unit.providers.fixtures import make_adapter, make_context, make_request

pytestmark = pytest.mark.unit


def test_missing_resource_id_not_accepted() -> None:
    adapter, _, _ = make_adapter()
    request = ProviderExecutionRequest(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        arguments=json_from_plain({"other": "x"}),
    )
    result = adapter.validate_execution(request)
    assert result.accepted is False
    assert result.error is not None
    assert result.error.kind is ErrorKind.VALIDATION
    assert result.error.code == "ref.validation.missing_resource_id"


def test_unknown_effect_not_accepted() -> None:
    adapter, _, _ = make_adapter()
    request = make_request(EffectRef(provider="other", action="nope", version="v1"))
    result = adapter.validate_execution(request)
    assert result.accepted is False
    assert result.error is not None
    assert result.error.kind is ErrorKind.UNSUPPORTED_CAPABILITY
    assert result.error.code == "ref.validation.unknown_effect"


def test_validate_does_not_consume_execute_script() -> None:
    adapter, _, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    adapter.validate_execution(make_request(EFFECT_MUTATE_PROVIDER_KEY))
    evidence = adapter.execute(
        make_context(),
        make_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.error is not None
    assert evidence.error.code == "ref.rejected.before_accept"


def test_validate_does_not_write_store() -> None:
    adapter, store, _ = make_adapter()
    adapter.validate_execution(make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert store.all_resources() == ()
