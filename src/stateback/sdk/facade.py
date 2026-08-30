"""Provider-native SDK facades over the canonical Stateback API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from stateback.application.auth import Role
from stateback.cli.config import load_project_config
from stateback.cli.project import ProjectFileError, find_project_root
from stateback.deployment.config import AuthConfig
from stateback.domain.refs import PrincipalRef
from stateback.sdk.async_client import AsyncOperationHandle, AsyncStatebackClient
from stateback.sdk.client import OperationHandle, StatebackClient


class LocalConfigurationError(RuntimeError):
    """The local Stateback project or caller credential is unavailable."""


def _local_caller(start: Path | None = None) -> tuple[str, str, PrincipalRef]:
    try:
        root = find_project_root(start or Path.cwd())
        config = load_project_config(root / "stateback.toml")
        auth_path = config.paths.auth
        if auth_path.is_symlink() or not auth_path.is_file():
            raise LocalConfigurationError("local Stateback auth file is unavailable")
        if auth_path.stat().st_size > 1024 * 1024:
            raise LocalConfigurationError("local Stateback auth file is too large")
        parsed = json.loads(auth_path.read_text(encoding="utf-8"))
        identities = AuthConfig.model_validate(parsed).identities
        callers = [
            item
            for item in identities
            if Role.CALLER in item.roles and Role.OPERATOR not in item.roles
        ]
        if len(callers) != 1:
            raise LocalConfigurationError(
                "local Stateback project must contain exactly one non-operator CALLER identity"
            )
        caller = callers[0]
        return (
            f"http://{config.dev.api_host}:{config.dev.api_port}",
            caller.token,
            PrincipalRef(
                type=caller.principal_type,
                id=caller.principal_id,
                display_name=caller.display_name,
            ),
        )
    except LocalConfigurationError:
        raise
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        ProjectFileError,
    ) as exc:
        raise LocalConfigurationError(
            "Local Stateback configuration is unavailable. Run `stateback init` first."
        ) from exc


def _local_connection(start: Path | None = None) -> tuple[str, str]:
    base_url, token, _ = _local_caller(start)
    return base_url, token


def _effect(action: str) -> dict[str, str]:
    return {"provider": "github", "action": action, "version": "v1"}


class GitHubOperations:
    def __init__(self, client: StatebackClient) -> None:
        self._client = client

    def _submit(
        self, action: str, arguments: dict[str, object], idempotency_key: str
    ) -> OperationHandle:
        return self._client.submit(
            effect=_effect(action),
            arguments=arguments,
            idempotency_key=idempotency_key,
        )

    def create_issue(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        idempotency_key: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> OperationHandle:
        arguments: dict[str, object] = {"owner": owner, "repo": repo, "title": title}
        if body is not None:
            arguments["body"] = body
        if labels is not None:
            arguments["labels"] = labels
        if assignees is not None:
            arguments["assignees"] = assignees
        return self._submit("create_issue", arguments, idempotency_key)

    def create_issue_comment(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
        idempotency_key: str,
    ) -> OperationHandle:
        return self._submit(
            "create_issue_comment",
            {"owner": owner, "repo": repo, "issue_number": issue_number, "body": body},
            idempotency_key,
        )

    def add_label(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        label: str,
        idempotency_key: str,
    ) -> OperationHandle:
        return self._submit(
            "add_label",
            {
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
            },
            idempotency_key,
        )

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        idempotency_key: str,
        body: str | None = None,
        draft: bool | None = None,
    ) -> OperationHandle:
        arguments: dict[str, object] = {
            "owner": owner,
            "repo": repo,
            "head": head,
            "base": base,
            "title": title,
        }
        if body is not None:
            arguments["body"] = body
        if draft is not None:
            arguments["draft"] = draft
        return self._submit("create_pull_request", arguments, idempotency_key)

    def merge_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        pull_number: int,
        head_sha: str,
        idempotency_key: str,
        merge_method: str | None = None,
    ) -> OperationHandle:
        arguments: dict[str, object] = {
            "owner": owner,
            "repo": repo,
            "pull_number": pull_number,
            "head_sha": head_sha,
        }
        if merge_method is not None:
            arguments["merge_method"] = merge_method
        return self._submit("merge_pull_request", arguments, idempotency_key)


class Stateback:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = StatebackClient(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
        self.github = GitHubOperations(self._client)

    @classmethod
    def local(cls, *, start: Path | None = None, timeout: float = 10.0) -> Stateback:
        base_url, token = _local_connection(start)
        return cls(base_url=base_url, token=token, timeout=timeout)

    @classmethod
    def from_env(cls) -> Stateback:
        base_url = os.environ.get("STATEBACK_API_URL")
        token = os.environ.get("STATEBACK_API_TOKEN")
        if not base_url or not token:
            raise LocalConfigurationError(
                "STATEBACK_API_URL and STATEBACK_API_TOKEN are required"
            )
        return cls(base_url=base_url, token=token)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Stateback:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class AsyncGitHubOperations:
    def __init__(self, client: AsyncStatebackClient) -> None:
        self._client = client

    async def _submit(
        self, action: str, arguments: dict[str, object], idempotency_key: str
    ) -> AsyncOperationHandle:
        return await self._client.submit(
            effect=_effect(action), arguments=arguments, idempotency_key=idempotency_key
        )

    async def create_issue(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        idempotency_key: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> AsyncOperationHandle:
        arguments: dict[str, object] = {"owner": owner, "repo": repo, "title": title}
        if body is not None:
            arguments["body"] = body
        if labels is not None:
            arguments["labels"] = labels
        if assignees is not None:
            arguments["assignees"] = assignees
        return await self._submit("create_issue", arguments, idempotency_key)

    async def create_issue_comment(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
        idempotency_key: str,
    ) -> AsyncOperationHandle:
        return await self._submit(
            "create_issue_comment",
            {"owner": owner, "repo": repo, "issue_number": issue_number, "body": body},
            idempotency_key,
        )

    async def add_label(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        label: str,
        idempotency_key: str,
    ) -> AsyncOperationHandle:
        return await self._submit(
            "add_label",
            {
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
            },
            idempotency_key,
        )

    async def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        idempotency_key: str,
        body: str | None = None,
        draft: bool | None = None,
    ) -> AsyncOperationHandle:
        arguments: dict[str, object] = {
            "owner": owner,
            "repo": repo,
            "head": head,
            "base": base,
            "title": title,
        }
        if body is not None:
            arguments["body"] = body
        if draft is not None:
            arguments["draft"] = draft
        return await self._submit("create_pull_request", arguments, idempotency_key)

    async def merge_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        pull_number: int,
        head_sha: str,
        idempotency_key: str,
        merge_method: str | None = None,
    ) -> AsyncOperationHandle:
        arguments: dict[str, object] = {
            "owner": owner,
            "repo": repo,
            "pull_number": pull_number,
            "head_sha": head_sha,
        }
        if merge_method is not None:
            arguments["merge_method"] = merge_method
        return await self._submit("merge_pull_request", arguments, idempotency_key)


class AsyncStateback:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = AsyncStatebackClient(
            base_url=base_url, token=token, timeout=timeout, transport=transport
        )
        self.github = AsyncGitHubOperations(self._client)

    @classmethod
    def local(
        cls, *, start: Path | None = None, timeout: float = 10.0
    ) -> AsyncStateback:
        base_url, token = _local_connection(start)
        return cls(base_url=base_url, token=token, timeout=timeout)

    @classmethod
    def from_env(cls) -> AsyncStateback:
        base_url = os.environ.get("STATEBACK_API_URL")
        token = os.environ.get("STATEBACK_API_TOKEN")
        if not base_url or not token:
            raise LocalConfigurationError(
                "STATEBACK_API_URL and STATEBACK_API_TOKEN are required"
            )
        return cls(base_url=base_url, token=token)

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> AsyncStateback:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()
