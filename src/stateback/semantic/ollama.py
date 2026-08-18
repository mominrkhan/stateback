"""Optional loopback-only Ollama structured-output adapter."""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlparse

from stateback.semantic.protocol import (
    ModelCompletion,
    SemanticModelInvalidResponse,
    SemanticModelUnavailable,
)

MAX_OLLAMA_RESPONSE_BYTES = 128 * 1024
HttpPost = Callable[[urllib.request.Request, float], bytes]


def _http_post(request: urllib.request.Request, timeout: float) -> bytes:
    parsed = urlparse(request.full_url)
    host = parsed.hostname
    port = parsed.port or 80
    if parsed.scheme != "http" or host is None:
        raise SemanticModelUnavailable("ollama_invalid_destination")
    try:
        addresses = {
            cast(str, item[4][0])
            for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
        if not addresses or any(
            not ipaddress.ip_address(address.split("%", 1)[0]).is_loopback
            for address in addresses
        ):
            raise SemanticModelUnavailable("ollama_non_loopback_destination")
        address = sorted(addresses)[0]
        connection = http.client.HTTPConnection(address, port, timeout=timeout)
        try:
            connection.request(
                cast(str, request.method),
                parsed.path or "/",
                body=cast(bytes | None, request.data),
                headers=dict(request.header_items()),
            )
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise SemanticModelUnavailable("ollama_http_error")
            body = response.read(MAX_OLLAMA_RESPONSE_BYTES + 1)
        finally:
            connection.close()
    except SemanticModelUnavailable:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SemanticModelUnavailable("ollama_unavailable") from exc
    if len(body) > MAX_OLLAMA_RESPONSE_BYTES:
        raise SemanticModelInvalidResponse("ollama_response_too_large")
    return body


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaSemanticModel:
    base_url: str
    model: str
    timeout_seconds: float = 20.0
    http_post: HttpPost = _http_post

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Ollama base_url must be a loopback HTTP origin")
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError("Ollama model must be 1-200 characters")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("Ollama timeout must be between 0 and 120 seconds")

    @property
    def provider(self) -> str:
        return "ollama"

    def complete(
        self, *, prompt: str, output_schema: dict[str, object]
    ) -> ModelCompletion:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": output_schema,
                "options": {"temperature": 0},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = self.http_post(request, self.timeout_seconds)
        try:
            envelope = json.loads(raw)
            message = envelope["message"]
            content = message["content"]
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
            raise SemanticModelInvalidResponse("ollama_invalid_envelope") from exc
        if not isinstance(content, str):
            raise SemanticModelInvalidResponse("ollama_invalid_content")
        return ModelCompletion(
            content=content, provider=self.provider, model=self.model
        )
