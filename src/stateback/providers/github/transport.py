"""Least-privilege GitHub REST transport with redacted failures."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
        api_url: str = "https://api.github.com",
        api_version: str = "2022-11-28",
    ) -> None:
        if not token:
            raise ValueError("GitHub token must be non-empty")
        if not api_url.startswith("https://"):
            raise ValueError("GitHub API URL must use HTTPS")
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
                "User-Agent": "stateback/0.0.0",
                "Content-Type": "application/json",
            },
        )
        opener = urllib.request.build_opener(_RejectRedirects())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return GitHubHttpResponse(
                    status=response.status,
                    headers=tuple(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return GitHubHttpResponse(
                status=exc.code,
                headers=tuple(exc.headers.items()),
                body=exc.read(),
            )


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
