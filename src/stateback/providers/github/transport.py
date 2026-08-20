"""Least-privilege GitHub REST transport with redacted failures."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from stateback import __version__

GITHUB_API_ORIGIN = "https://api.github.com"
MAX_GITHUB_RESPONSE_BYTES = 1024 * 1024


class GitHubResponseTooLarge(RuntimeError):
    """A provider response exceeded the bounded transport envelope."""


@dataclass(frozen=True, slots=True, kw_only=True)
class GitHubHttpResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name: str) -> str | None:
        lowered = name.lower()
        for key, value in self.headers:
            if key.lower() == lowered:
                return value
        return None


@runtime_checkable
class GitHubTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
    ) -> GitHubHttpResponse: ...


class UrllibGitHubTransport:
    def __init__(
        self,
        *,
        token: str,
        api_url: str = GITHUB_API_ORIGIN,
        api_version: str = "2022-11-28",
    ) -> None:
        if not token:
            raise ValueError("GitHub token must be non-empty")
        parsed = urlparse(api_url)
        if (
            api_url != GITHUB_API_ORIGIN
            or parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(character) < 32 for character in api_url)
        ):
            raise ValueError(
                "GitHub API URL must be the exact credential-free HTTPS origin"
            )
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._api_version = api_version

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
    ) -> GitHubHttpResponse:
        request = urllib.request.Request(
            f"{self._api_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": self._api_version,
                "User-Agent": f"stateback/{__version__}",
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return GitHubHttpResponse(
                    status=response.status,
                    headers=tuple(response.headers.items()),
                    body=_read_bounded(response),
                )
        except urllib.error.HTTPError as exc:
            return GitHubHttpResponse(
                status=exc.code,
                headers=tuple(exc.headers.items()),
                body=_read_bounded(exc),
            )


def _read_bounded(response: object) -> bytes:
    read = getattr(response, "read", None)
    if not callable(read):
        raise TypeError("GitHub response is not readable")
    body = read(MAX_GITHUB_RESPONSE_BYTES + 1)
    if not isinstance(body, bytes):
        raise TypeError("GitHub response body must be bytes")
    if len(body) > MAX_GITHUB_RESPONSE_BYTES:
        raise GitHubResponseTooLarge("GitHub response exceeded the supported size")
    return body


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Do not forward authorization headers to redirect destinations."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        del req, fp, code, msg, headers, newurl
        return None
