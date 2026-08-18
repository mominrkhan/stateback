from __future__ import annotations

import http.client
import json
import urllib.request

import pytest

from stateback.semantic import (
    AuditSummaryService,
    OllamaSemanticModel,
    SemanticModelInvalidResponse,
    SemanticModelUnavailable,
    SemanticStatus,
)
from tests.unit.application.fixtures import operation

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:11434",
        "http://example.com:11434",
        "http://user:password@localhost:11434",
        "http://localhost:11434/path",
    ],
)
def test_only_credential_free_loopback_origin_is_allowed(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaSemanticModel(base_url=url, model="qwen3")


def test_ollama_uses_nonstreaming_schema_without_credentials() -> None:
    observed: list[tuple[urllib.request.Request, float]] = []

    def post(request: urllib.request.Request, timeout: float) -> bytes:
        observed.append((request, timeout))
        return json.dumps(
            {"message": {"role": "assistant", "content": '{"status":"ABSTAINED"}'}}
        ).encode()

    model = OllamaSemanticModel(
        base_url="http://127.0.0.1:11434",
        model="qwen3",
        timeout_seconds=3,
        http_post=post,
    )
    completion = model.complete(prompt="safe prompt", output_schema={"type": "object"})
    request, timeout = observed[0]
    assert isinstance(request.data, bytes)
    payload = json.loads(request.data)
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    assert request.get_header("Authorization") is None
    assert payload["stream"] is False
    assert payload["format"] == {"type": "object"}
    assert payload["options"] == {"temperature": 0}
    assert timeout == 3
    assert completion.provider == "ollama"
    assert completion.model == "qwen3"


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"message":{"content":1}}'])
def test_invalid_ollama_envelope_is_rejected(body: bytes) -> None:
    model = OllamaSemanticModel(
        base_url="http://localhost:11434",
        model="qwen3",
        http_post=lambda _request, _timeout: body,
    )
    with pytest.raises(SemanticModelInvalidResponse):
        model.complete(prompt="prompt", output_schema={"type": "object"})


def test_ollama_timeout_becomes_safe_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def request(self, *_args: object, **_kwargs: object) -> None:
            raise TimeoutError

        def close(self) -> None:
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", TimeoutConnection)
    model = OllamaSemanticModel(base_url="http://127.0.0.1:11434", model="qwen3")
    result = AuditSummaryService(semantic_model=model).summarize(
        operation=operation(), audit=()
    )
    assert result.status is SemanticStatus.UNAVAILABLE
    assert result.reason_code == "semantic_model_unavailable"


def test_invalid_ollama_utf8_becomes_invalid_result() -> None:
    model = OllamaSemanticModel(
        base_url="http://localhost:11434",
        model="qwen3",
        http_post=lambda _request, _timeout: b"\xff",
    )
    result = AuditSummaryService(semantic_model=model).summarize(
        operation=operation(), audit=()
    )
    assert result.status is SemanticStatus.INVALID
    assert result.reason_code == "semantic_model_invalid_envelope"


def test_environment_proxy_cannot_receive_ollama_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected: list[tuple[str, int]] = []
    bodies: list[bytes | None] = []

    class Response:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b'{"message":{"content":"{\\"status\\":\\"ABSTAINED\\"}"}}'

    class DirectConnection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            del timeout
            connected.append((host, port))

        def request(
            self,
            _method: str,
            _path: str,
            body: bytes | None,
            headers: dict[str, str],
        ) -> None:
            del headers
            bodies.append(body)

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setenv("HTTP_PROXY", "http://198.51.100.10:9999")
    monkeypatch.setattr(http.client, "HTTPConnection", DirectConnection)
    model = OllamaSemanticModel(base_url="http://127.0.0.1:11434", model="qwen3")
    model.complete(prompt="sensitive audit prompt", output_schema={"type": "object"})
    assert connected == [("127.0.0.1", 11434)]
    assert len(bodies) == 1
    assert bodies[0] is not None and b"sensitive audit prompt" in bodies[0]


def test_ollama_redirect_is_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[str] = []
    requests = 0

    class RedirectResponse:
        status = 302

        def read(self, _limit: int) -> bytes:
            return b""

    class RedirectConnection:
        def __init__(self, host: str, _port: int, *, timeout: float) -> None:
            del timeout
            connected.append(host)

        def request(self, *_args: object, **_kwargs: object) -> None:
            nonlocal requests
            requests += 1

        def getresponse(self) -> RedirectResponse:
            return RedirectResponse()

        def close(self) -> None:
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", RedirectConnection)
    model = OllamaSemanticModel(base_url="http://127.0.0.1:11434", model="qwen3")
    with pytest.raises(SemanticModelUnavailable, match="ollama_http_error"):
        model.complete(prompt="must remain local", output_schema={"type": "object"})
    assert connected == ["127.0.0.1"]
    assert requests == 1
