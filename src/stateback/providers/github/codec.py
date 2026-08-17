"""Pure GitHub request and issue-identity encoding."""

from __future__ import annotations

import json
from urllib.parse import unquote, urlparse

from stateback.domain.capability import CompensationRequest, ProviderExecutionContext
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonArray, JsonObject, JsonValue

type IssueIdentity = tuple[str, str, int, str, str]
type IssueResource = tuple[str, str, int]


def validate_arguments(arguments: JsonValue) -> str | None:
    if not isinstance(arguments, JsonObject):
        return "github.validation.arguments_not_object"
    data = arguments.as_dict()
    allowed = {"owner", "repo", "title", "body", "labels", "assignees"}
    if set(data) - allowed:
        return "github.validation.unknown_argument"
    for field in ("owner", "repo", "title"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"github.validation.invalid_{field}"
    if len(required_str(data, "title")) > 256:
        return "github.validation.title_too_long"
    body = data.get("body")
    if body is not None and not isinstance(body, str):
        return "github.validation.invalid_body"
    for field in ("labels", "assignees"):
        value = data.get(field)
        if value is not None and (
            not isinstance(value, JsonArray)
            or any(not isinstance(item, str) or not item for item in value.items)
        ):
            return f"github.validation.invalid_{field}"
    return None


def argument_map(arguments: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(arguments, JsonObject):
        raise ContractValidationError(
            "illegal_combination", "validated GitHub arguments must be an object"
        )
    return arguments.as_dict()


def required_str(data: dict[str, JsonValue], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str):
        raise ContractValidationError(
            "illegal_combination", f"validated GitHub {field} must be a string"
        )
    return value


def operation_marker(context: ProviderExecutionContext) -> str:
    return f"<!-- stateback-operation:{context.operation_id.value} -->"


def create_payload(data: dict[str, JsonValue], marker: str) -> dict[str, object]:
    body_value = data.get("body")
    body = body_value if isinstance(body_value, str) else ""
    payload: dict[str, object] = {
        "title": required_str(data, "title"),
        "body": f"{body}\n\n{marker}" if body else marker,
    }
    for field in ("labels", "assignees"):
        value = data.get(field)
        if isinstance(value, JsonArray):
            payload[field] = list(value.items)
    return payload


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_object(body: bytes) -> dict[str, object] | None:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in parsed.items()}


def issue_identity(
    parsed: dict[str, object] | None,
    *,
    owner: str,
    repo: str,
    expected_number: int | None = None,
) -> IssueIdentity | None:
    if parsed is None:
        return None
    issue_id = parsed.get("id")
    number = parsed.get("number")
    html_url = parsed.get("html_url")
    repository_url = parsed.get("repository_url")
    state = parsed.get("state")
    if (
        isinstance(issue_id, bool)
        or not isinstance(issue_id, int)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or not isinstance(html_url, str)
        or not isinstance(repository_url, str)
        or state not in {"open", "closed"}
        or (expected_number is not None and number != expected_number)
        or not _matches_issue_url(html_url, owner, repo, number)
        or not _matches_repository_url(repository_url, owner, repo)
    ):
        return None
    return (
        f"github:issue:{issue_id}",
        f"{owner}/{repo}#{number}",
        number,
        html_url,
        state,
    )


def _https_path(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return unquote(parsed.path).rstrip("/").casefold()


def _matches_issue_url(url: str, owner: str, repo: str, number: int) -> bool:
    path = _https_path(url)
    expected = f"/{owner}/{repo}/issues/{number}".casefold()
    return path is not None and path.endswith(expected)


def _matches_repository_url(url: str, owner: str, repo: str) -> bool:
    path = _https_path(url)
    expected = f"/repos/{owner}/{repo}".casefold()
    return path is not None and path.endswith(expected)


def first_issue_resource(
    external_resource_ids: tuple[str, ...],
) -> IssueResource | None:
    for resource in external_resource_ids:
        parsed = parse_resource(resource)
        if parsed is not None:
            return parsed
    return None


def parse_resource(resource: str) -> IssueResource | None:
    try:
        repository, number_raw = resource.rsplit("#", 1)
        owner, repo = repository.split("/", 1)
        number = int(number_raw)
    except (ValueError, TypeError):
        return None
    if not owner or not repo or number < 1:
        return None
    return owner, repo, number


def find_marked_issue(
    body: bytes,
    *,
    marker: str,
    resource: IssueResource | None,
) -> IssueIdentity | None:
    parsed = parse_object(body)
    candidates: list[dict[str, object]] = []
    if resource is not None and parsed is not None:
        candidates = [parsed]
    elif parsed is not None:
        items = parsed.get("items")
        if isinstance(items, list):
            candidates = [item for item in items if isinstance(item, dict)]
    for item in candidates:
        issue_body = item.get("body")
        repository_url = item.get("repository_url")
        if not isinstance(issue_body, str) or marker not in issue_body:
            continue
        if resource is not None:
            owner, repo, expected_number = resource
        elif isinstance(repository_url, str) and "/repos/" in repository_url:
            suffix = repository_url.rsplit("/repos/", 1)[1]
            parts = suffix.split("/", 1)
            if len(parts) != 2:
                continue
            owner, repo = parts
            expected_number = None
        else:
            continue
        identity = issue_identity(
            item,
            owner=owner,
            repo=repo,
            expected_number=expected_number,
        )
        if identity is not None:
            return identity
    return None


def resource_from_original_evidence(
    request: CompensationRequest,
) -> IssueResource | None:
    for evidence in request.original_evidence:
        resource = first_issue_resource(evidence.external_resource_ids)
        if resource is not None:
            return resource
    return None
