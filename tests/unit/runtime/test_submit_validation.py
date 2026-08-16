from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef
from stateback.policy import AllowAllPolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_READ_RESOURCE,
)
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import (
    PHASE5_ENVIRONMENT,
    SubmitCommand,
    SubmitIds,
    SynchronousRuntime,
)
from stateback.runtime.results import RuntimeDisposition
from tests.unit.domain.fixtures import OP_ID, REQUESTER
from tests.unit.runtime.fixtures import ARGUMENTS, CLOCK

pytestmark = pytest.mark.unit


def _ids() -> SubmitIds:
    from stateback.domain.ids import OpaqueId

    def oid(n: int) -> OpaqueId:
        return OpaqueId(value=f"00000000-0000-4000-8000-{n:012x}")

    return SubmitIds(
        operation_id=OP_ID,
        created_audit_event_id=oid(0x21),
        policy_decision_id=oid(0x22),
        policy_audit_event_id=oid(0x23),
        policy_transition_audit_event_id=oid(0x24),
        allow_outbox_event_id=oid(0x25),
        approval_id=oid(0x26),
        approval_audit_event_id=oid(0x27),
    )


def _runtime(registry: CapabilityRegistry) -> tuple[SynchronousRuntime, MagicMock]:
    factory = MagicMock()
    runtime = SynchronousRuntime(
        session_factory=factory,
        registry=registry,
        policy_engine=AllowAllPolicyEngine(),
        clock=CLOCK,
    )
    return runtime, factory


def _command(**kwargs: object) -> SubmitCommand:
    payload: dict[str, object] = {
        "effect": EFFECT_MUTATE_PROVIDER_KEY,
        "arguments": ARGUMENTS,
        "requester": REQUESTER,
        "metadata": (),
        "ids": _ids(),
        "correlation_id": None,
        "deployment_environment": PHASE5_ENVIRONMENT,
    }
    payload.update(kwargs)
    return SubmitCommand(**payload)  # type: ignore[arg-type]


def test_unregistered_effect_rejected_without_persist() -> None:
    runtime, factory = _runtime(CapabilityRegistry())
    result = runtime.submit(
        _command(
            effect=EffectRef(provider="nope", action="missing", version="v1"),
        )
    )
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "unregistered_effect"
    factory.assert_not_called()


def test_read_only_effect_rejected() -> None:
    store = ReferenceStore()
    adapter = ReferenceAdapter(store=store, clock=CLOCK)
    registry = CapabilityRegistry()
    registry.register(adapter)
    runtime, factory = _runtime(registry)
    result = runtime.submit(_command(effect=EFFECT_READ_RESOURCE))
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "read_only_effect_not_consequential"
    factory.assert_not_called()


def test_secret_metadata_rejected() -> None:
    store = ReferenceStore()
    adapter = ReferenceAdapter(store=store, clock=CLOCK)
    registry = CapabilityRegistry()
    registry.register(adapter)
    runtime, factory = _runtime(registry)
    result = runtime.submit(_command(metadata=(("api_key", "secret-value"),)))
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "secret_field"
    factory.assert_not_called()


def test_adapter_validation_failure_rejected() -> None:
    store = ReferenceStore()
    adapter = ReferenceAdapter(store=store, clock=CLOCK)
    registry = CapabilityRegistry()
    registry.register(adapter)
    runtime, factory = _runtime(registry)
    result = runtime.submit(_command(arguments=json_from_plain({"name": "no-id"})))
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "validation_rejected"
    assert result.validation_error is not None
    factory.assert_not_called()
