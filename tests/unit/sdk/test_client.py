from __future__ import annotations

import json
import threading

import httpx
import pytest

from stateback.sdk import (
    StatebackClient,
    StatebackClientError,
    StatebackTransportError,
    WaitOutcome,
)
from tests.unit.application.fixtures import operation

pytestmark = pytest.mark.unit


def _response(payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload).encode())


def test_submit_preserves_idempotency_and_returns_handle() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(operation().to_wire(), 202)

    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(handler),
    )
    handle = client.submit(
        effect={"provider": "reference", "action": "create_resource", "version": "v1"},
        arguments={"name": "demo"},
        idempotency_key="request-1",
    )
    assert handle.operation_id == str(operation().operation_id)
    assert handle.initial_status.state == "READY"
    assert seen[0].headers["idempotency-key"] == "request-1"
    assert b"safe-token" not in seen[0].content
    client.close()


def test_unknown_future_state_is_not_reinterpreted() -> None:
    payload = operation().to_wire()
    payload["state"] = "FUTURE_STATE"
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(lambda _request: _response(payload)),
    )
    status = client.get_operation(str(operation().operation_id))
    assert status.state == "FUTURE_STATE"
    assert status.known_state is None
    assert not status.is_forward_terminal
    client.close()


def test_wait_timeout_does_not_become_operation_failure() -> None:
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(
            lambda _request: _response(operation().to_wire())
        ),
    )
    result = client.get_operation(str(operation().operation_id))
    handle = client.submit(
        effect={"provider": "reference", "action": "create_resource", "version": "v1"},
        arguments={},
        idempotency_key="request-1",
    )
    waited = handle.wait(timeout=0)
    assert waited.outcome is WaitOutcome.TIMED_OUT
    assert waited.operation.state == result.state == "READY"
    client.close()


def test_wait_returns_only_after_a_terminal_operation_state() -> None:
    ready = operation().to_wire()
    succeeded = operation().to_wire()
    succeeded["state"] = "SUCCEEDED"
    responses = iter((ready, ready, succeeded))
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(lambda _request: _response(next(responses))),
    )
    handle = client.submit(
        effect={"provider": "reference", "action": "create_resource", "version": "v1"},
        arguments={},
        idempotency_key="request-terminal",
    )
    waited = handle.wait(timeout=1, poll_interval=0.001)
    assert waited.outcome is WaitOutcome.COMPLETED
    assert waited.operation.state == "SUCCEEDED"
    client.close()


def test_wait_cancellation_is_not_an_operation_outcome() -> None:
    cancelled = threading.Event()
    cancelled.set()
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(
            lambda _request: _response(operation().to_wire())
        ),
    )
    handle = client.submit(
        effect={"provider": "reference", "action": "create_resource", "version": "v1"},
        arguments={},
        idempotency_key="request-cancelled",
    )
    waited = handle.wait(timeout=1, cancel=cancelled)
    assert waited.outcome is WaitOutcome.CANCELLED
    assert waited.operation.state == "READY"
    client.close()


def test_api_error_is_distinct_from_operation_status() -> None:
    error = {
        "contract_version": "v1",
        "error": {"code": "unavailable", "retryable": True},
    }
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(lambda _request: _response(error, 503)),
    )
    with pytest.raises(StatebackClientError) as caught:
        client.get_operation(str(operation().operation_id))
    assert caught.value.retryable
    assert caught.value.status_code == 503
    client.close()


def test_malformed_success_is_a_transport_error_not_an_operation_outcome() -> None:
    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(
            lambda _request: _response({"contract_version": "v1", "state": "SUCCEEDED"})
        ),
    )
    with pytest.raises(StatebackTransportError, match="malformed_response"):
        client.get_operation(str(operation().operation_id))
    client.close()
