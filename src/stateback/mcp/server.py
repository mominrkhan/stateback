"""MCP tools preserve the public operation path and never call providers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from stateback.application.auth import AuthenticatedIdentity
from stateback.application.input_validation import bounded_json_from_plain
from stateback.application.models import SubmitOperationRequest
from stateback.application.service import ApplicationService
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import EffectRef
from stateback.sdk import StatebackClient

IdempotencyKey = Annotated[str, Field(min_length=1, max_length=200)]
ProviderName = Annotated[str, Field(min_length=1, max_length=100)]
PositiveNumber = Annotated[int, Field(gt=0)]
HeadSha = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{40}$")]
MergeMethod = Literal["merge", "squash", "rebase"]


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class McpSubmitInput(_StrictInput):
    provider: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    effect_version: str = Field(min_length=1, max_length=50)
    arguments: Any
    idempotency_key: str = Field(min_length=1, max_length=200)
    deployment_environment: str = Field(min_length=1, max_length=100)
    metadata: dict[str, str] = Field(default_factory=dict)


class StatebackMcpTools:
    """Testable MCP tool logic with an authenticated session identity."""

    def __init__(
        self, *, service: ApplicationService, identity: AuthenticatedIdentity
    ) -> None:
        self._service = service
        self._identity = identity

    def submit(self, raw: object) -> dict[str, object]:
        parsed = McpSubmitInput.model_validate(raw)
        operation = self._service.submit(
            identity=self._identity,
            idempotency_key=parsed.idempotency_key,
            request=SubmitOperationRequest(
                effect=EffectRef(
                    provider=parsed.provider,
                    action=parsed.action,
                    version=parsed.effect_version,
                ),
                arguments=bounded_json_from_plain(parsed.arguments),
                metadata=tuple(sorted(parsed.metadata.items())),
                deployment_environment=parsed.deployment_environment,
            ),
        )
        return operation.to_wire()

    def status(self, operation_id: str) -> dict[str, object]:
        return self._service.get_operation(
            self._identity, OpaqueId.from_wire(operation_id)
        ).to_wire()

    def audit(
        self, operation_id: str, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, object]:
        return self._service.audit_page(
            identity=self._identity,
            operation_id=OpaqueId.from_wire(operation_id),
            after_sequence=after_sequence,
            limit=limit,
        ).to_wire()


class ApiMcpTools:
    """Testable public-API MCP logic; never interprets transport failure as state."""

    def __init__(self, client: StatebackClient) -> None:
        self._client = client

    def submit_github(
        self, action: str, arguments: dict[str, object], key: str
    ) -> dict[str, object]:
        handle = self._client.submit(
            effect={"provider": "github", "action": action, "version": "v1"},
            arguments=arguments,
            idempotency_key=key,
        )
        return {
            "operation_id": handle.operation_id,
            "state": handle.initial_status.state,
            "accepted": True,
            "provider_outcome": "NOT_ESTABLISHED",
            "next": "Call stateback_operation_status for durable outcome.",
        }

    def status(self, operation_id: str) -> dict[str, object]:
        return dict(self._client.get_operation(operation_id).raw)

    def audit(
        self, operation_id: str, *, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, object]:
        return self._client.get_audit(
            operation_id, after_sequence=after_sequence, limit=limit
        )


def create_mcp_server(
    *, service: ApplicationService, identity: AuthenticatedIdentity
) -> MCPServer[None]:
    tools = StatebackMcpTools(service=service, identity=identity)
    server: MCPServer[None] = MCPServer(
        "stateback",
        version="v1",
        instructions=(
            "Stateback creates durable managed operations. Tool acceptance is not "
            "proof that an external effect succeeded; inspect operation state."
        ),
    )

    @server.tool(
        name="stateback_submit_operation",
        description=(
            "Create a durable Stateback operation through policy and journaling; "
            "returns operation identity and current state, not provider success."
        ),
        structured_output=True,
    )
    def submit_operation(
        provider: str,
        action: str,
        effect_version: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        deployment_environment: str = "production",
        metadata: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return tools.submit(
            {
                "provider": provider,
                "action": action,
                "effect_version": effect_version,
                "arguments": arguments,
                "idempotency_key": idempotency_key,
                "deployment_environment": deployment_environment,
                "metadata": metadata or {},
            }
        )

    @server.tool(
        name="stateback_get_operation",
        description="Read canonical operation state without causing an external effect.",
        structured_output=True,
    )
    def get_operation(operation_id: str) -> dict[str, object]:
        return tools.status(operation_id)

    @server.tool(
        name="stateback_get_audit",
        description="Read ordered durable audit history without changing operation state.",
        structured_output=True,
    )
    def get_audit(
        operation_id: str, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, object]:
        return tools.audit(operation_id, after_sequence, limit)

    return server


def create_api_mcp_server(client: StatebackClient) -> MCPServer[None]:
    """Create the installed stdio server backed only by the public Stateback API."""

    tools = ApiMcpTools(client)
    server: MCPServer[None] = MCPServer(
        "stateback",
        version="v1",
        instructions=(
            "Each mutating tool submits a durable Stateback operation through policy. "
            "Acceptance does not prove the provider action succeeded. Use the status "
            "and audit tools to observe final, pending, or UNKNOWN outcomes."
        ),
    )

    def submit(
        action: str, arguments: dict[str, object], key: str
    ) -> dict[str, object]:
        return tools.submit_github(action, arguments, key)

    @server.tool(
        name="stateback_github_create_issue",
        description="Submit a durable GitHub issue operation. Acceptance is not provider success; check operation status.",
        structured_output=True,
    )
    def create_issue(
        owner: ProviderName,
        repo: ProviderName,
        title: str,
        idempotency_key: IdempotencyKey,
        body: str = "",
    ) -> dict[str, object]:
        return submit(
            "create_issue",
            {"owner": owner, "repo": repo, "title": title, "body": body},
            idempotency_key,
        )

    @server.tool(
        name="stateback_github_create_issue_comment",
        description="Submit a durable GitHub issue-comment operation. Acceptance is not provider success; check operation status.",
        structured_output=True,
    )
    def create_issue_comment(
        owner: ProviderName,
        repo: ProviderName,
        issue_number: PositiveNumber,
        body: str,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, object]:
        return submit(
            "create_issue_comment",
            {"owner": owner, "repo": repo, "issue_number": issue_number, "body": body},
            idempotency_key,
        )

    @server.tool(
        name="stateback_github_add_label",
        description="Submit a durable GitHub label operation. Acceptance is not provider success; check operation status.",
        structured_output=True,
    )
    def add_label(
        owner: ProviderName,
        repo: ProviderName,
        issue_number: PositiveNumber,
        label: str,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, object]:
        return submit(
            "add_label",
            {
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
                "label": label,
            },
            idempotency_key,
        )

    @server.tool(
        name="stateback_github_create_pull_request",
        description="Submit a durable GitHub pull-request operation. Acceptance is not provider success; check operation status.",
        structured_output=True,
    )
    def create_pull_request(
        owner: ProviderName,
        repo: ProviderName,
        head: str,
        base: str,
        title: str,
        idempotency_key: IdempotencyKey,
        body: str = "",
        draft: bool = False,
    ) -> dict[str, object]:
        return submit(
            "create_pull_request",
            {
                "owner": owner,
                "repo": repo,
                "head": head,
                "base": base,
                "title": title,
                "body": body,
                "draft": draft,
            },
            idempotency_key,
        )

    @server.tool(
        name="stateback_github_merge_pull_request",
        description="Submit an approval-gated durable GitHub merge bound to an expected head SHA. Acceptance is not provider success; check operation status.",
        structured_output=True,
    )
    def merge_pull_request(
        owner: ProviderName,
        repo: ProviderName,
        pull_number: PositiveNumber,
        head_sha: HeadSha,
        idempotency_key: IdempotencyKey,
        merge_method: MergeMethod = "merge",
    ) -> dict[str, object]:
        return submit(
            "merge_pull_request",
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "head_sha": head_sha,
                "merge_method": merge_method,
            },
            idempotency_key,
        )

    @server.tool(
        name="stateback_operation_status",
        description="Read canonical durable operation status, including UNKNOWN and approval states.",
        structured_output=True,
    )
    def operation_status(operation_id: str) -> dict[str, object]:
        return tools.status(operation_id)

    @server.tool(
        name="stateback_operation_audit",
        description="Read ordered durable operation audit evidence without causing an external effect.",
        structured_output=True,
    )
    def operation_audit(
        operation_id: str, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, object]:
        return tools.audit(operation_id, after_sequence=after_sequence, limit=limit)

    return server
