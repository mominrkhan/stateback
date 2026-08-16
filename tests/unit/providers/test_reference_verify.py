from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, ErrorKind, VerificationTarget
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_EVENTUAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
)
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from tests.unit.providers.fixtures import (
    make_adapter,
    make_context,
    make_request,
    make_verify_request,
)

pytestmark = pytest.mark.unit


def test_verify_applied_after_lost_execute_response() -> None:
    adapter, _, _ = make_adapter()
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    lost = adapter.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert lost.outcome is EffectOutcome.UNKNOWN
    assert lost.external_operation_id is None
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.APPLIED
    assert evidence.error is None


def test_verify_not_applied_when_never_executed() -> None:
    adapter, _, _ = make_adapter()
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.NOT_APPLIED


def test_verify_timeout_script_is_unknown() -> None:
    adapter, _, _ = make_adapter()
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_TRANSPORT)
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.code == "ref.verify.transport"


def test_verify_inconsistent_is_unknown() -> None:
    adapter, _, _ = make_adapter()
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_PROVIDER_KEY),
    )
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.PROVIDER_INCONSISTENT
    assert evidence.error.code == "ref.verify.inconsistent"


def test_verify_none_capability_is_unsupported() -> None:
    adapter, _, _ = make_adapter()
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_NONE),
    )
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.kind is ErrorKind.UNSUPPORTED_CAPABILITY
    assert evidence.error.code == "ref.unsupported.verification"


def test_eventual_not_found_is_unknown() -> None:
    adapter, _, _ = make_adapter()
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_EVENTUAL),
    )
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.code == "ref.verify.visibility_window"


def test_eventual_found_inside_visibility_window_is_unknown() -> None:
    adapter, _, _ = make_adapter(visibility_delay_seconds=60)
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_EVENTUAL))
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_EVENTUAL),
    )
    assert evidence.outcome is EffectOutcome.UNKNOWN
    assert evidence.error is not None
    assert evidence.error.code == "ref.verify.visibility_window"


def test_eventual_found_after_visibility_window_is_applied() -> None:
    adapter, _, clock = make_adapter(visibility_delay_seconds=60)
    adapter.execute(make_context(), make_request(EFFECT_MUTATE_EVENTUAL))
    clock.advance(60)
    evidence = adapter.verify(
        make_context(),
        make_verify_request(EFFECT_MUTATE_EVENTUAL),
    )
    assert evidence.outcome is EffectOutcome.APPLIED


def test_verify_does_not_write_store() -> None:
    adapter, store, _ = make_adapter()
    before = store.all_resources()
    adapter.verify(make_context(), make_verify_request(EFFECT_MUTATE_PROVIDER_KEY))
    assert store.all_resources() == before


def test_verify_does_not_return_applied_merely_because_execute_was_called_on_another_store() -> (
    None
):
    adapter_a, _, _ = make_adapter()
    adapter_b, _, _ = make_adapter()
    adapter_a.execute(make_context(), make_request(EFFECT_MUTATE_PROVIDER_KEY))
    evidence = adapter_b.verify(
        make_context(),
        make_verify_request(
            EFFECT_MUTATE_PROVIDER_KEY,
            target=VerificationTarget.ORIGINAL_EFFECT,
        ),
    )
    assert evidence.outcome is not EffectOutcome.APPLIED
    assert evidence.outcome is EffectOutcome.NOT_APPLIED
