from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from stateback import AsyncStateback, Stateback
from stateback.sdk.facade import LocalConfigurationError, _local_connection
from tests.unit.application.fixtures import operation

pytestmark = pytest.mark.unit


def _response(payload: object, status: int = 202) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload).encode())


def test_provider_native_sync_methods_submit_canonical_effects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(operation().to_wire())

    stateback = Stateback(
        base_url="https://stateback.test",
        token="caller-token",
        transport=httpx.MockTransport(handler),
    )
    handle = stateback.github.merge_pull_request(
        owner="acme",
        repo="sandbox",
        pull_number=17,
        head_sha="a" * 40,
        merge_method="squash",
        idempotency_key="agent-run-1-merge-17",
    )
    payload = json.loads(seen[0].content)
    assert handle.operation_id == str(operation().operation_id)
    assert payload["effect"] == {
        "provider": "github",
        "action": "merge_pull_request",
        "version": "v1",
    }
    assert payload["arguments"]["head_sha"] == "a" * 40
    assert seen[0].headers["idempotency-key"] == "agent-run-1-merge-17"
    assert b"caller-token" not in seen[0].content
    stateback.close()


def test_provider_native_methods_require_stable_nonempty_key() -> None:
    stateback = Stateback(
        base_url="https://stateback.test",
        token="caller-token",
        transport=httpx.MockTransport(lambda _request: _response({})),
    )
    with pytest.raises(ValueError, match="stable across retries"):
        stateback.github.create_issue(
            owner="acme", repo="sandbox", title="demo", idempotency_key=""
        )
    stateback.close()


def test_provider_native_async_methods_use_async_transport() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(operation().to_wire())

    async def exercise() -> None:
        stateback = AsyncStateback(
            base_url="https://stateback.test",
            token="caller-token",
            transport=httpx.MockTransport(handler),
        )
        handle = await stateback.github.add_label(
            owner="acme",
            repo="sandbox",
            issue_number=42,
            label="safe",
            idempotency_key="agent-run-1-label-42",
        )
        assert handle.operation_id == str(operation().operation_id)
        assert json.loads(seen[0].content)["effect"]["action"] == "add_label"
        await stateback.close()

    asyncio.run(exercise())


def test_local_discovery_selects_non_operator_caller(tmp_path: Path) -> None:
    state = tmp_path / ".stateback"
    state.mkdir()
    (tmp_path / "stateback.toml").write_text(
        """schema_version = 1
[project]
name = "test"
[dev]
api_port = 8123
[paths]
auth = ".stateback/auth.json"
""",
        encoding="utf-8",
    )
    (state / "auth.json").write_text(
        json.dumps(
            {
                "identities": [
                    {
                        "token": "caller-only",
                        "principal_type": "AGENT",
                        "principal_id": "caller",
                        "roles": ["CALLER", "READER"],
                    },
                    {
                        "token": "operator-secret",
                        "principal_type": "OPERATOR",
                        "principal_id": "operator",
                        "roles": ["OPERATOR", "APPROVER"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    base_url, token = _local_connection(tmp_path)
    assert base_url == "http://127.0.0.1:8123"
    assert token == "caller-only"


def test_local_discovery_has_actionable_uninitialized_error(tmp_path: Path) -> None:
    with pytest.raises(LocalConfigurationError, match="stateback init"):
        _local_connection(tmp_path)


def test_environment_construction_is_stateback_api_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATEBACK_API_URL", "https://stateback.test")
    monkeypatch.setenv("STATEBACK_API_TOKEN", "stateback-caller")
    client = Stateback.from_env()
    client.close()


def test_async_wait_preserves_task_cancellation() -> None:
    async def exercise() -> None:
        stateback = AsyncStateback(
            base_url="https://stateback.test",
            token="caller-token",
            transport=httpx.MockTransport(
                lambda _request: _response(operation().to_wire())
            ),
        )
        handle = await stateback.github.create_issue(
            owner="acme",
            repo="sandbox",
            title="demo",
            idempotency_key="async-cancel",
        )
        task = asyncio.create_task(handle.wait(timeout=10, poll_interval=10))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stateback.close()

    asyncio.run(exercise())
