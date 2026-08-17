"""Pure normalization of GitHub HTTP response status and retry metadata."""

from __future__ import annotations

from stateback.domain.enums import ErrorKind
from stateback.providers.github.transport import GitHubHttpResponse


def retry_after(response: GitHubHttpResponse) -> int | None:
    raw = response.header("retry-after")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def classify_http(
    response: GitHubHttpResponse,
) -> tuple[ErrorKind, str, bool, bool]:
    status = response.status
    if status == 401:
        return ErrorKind.AUTHENTICATION, "github.auth.rejected", False, True
    if status in {403, 429} and (
        response.header("retry-after") is not None
        or response.header("x-ratelimit-remaining") == "0"
        or status == 429
    ):
        return ErrorKind.RATE_LIMITED, "github.rate_limited", True, True
    if status in {403, 404}:
        return ErrorKind.AUTHORIZATION, "github.authorization.rejected", False, True
    if status in {400, 410, 422}:
        return ErrorKind.PROVIDER_REJECTED, "github.request.rejected", False, True
    if 500 <= status <= 599:
        return ErrorKind.PROVIDER_UNAVAILABLE, "github.server.ambiguous", True, False
    # Once a request crossed the provider boundary, an undocumented status is
    # not proof that the effect was rejected. Preserve ambiguity unless the
    # provider contract explicitly establishes a conclusive status above.
    return ErrorKind.PROVIDER_REJECTED, "github.http.ambiguous", False, False
