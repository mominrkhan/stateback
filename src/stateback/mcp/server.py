"""MCP tools preserve the public operation path and never call providers."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict, Field

from stateback.application.auth import AuthenticatedIdentity
from stateback.application.input_validation import bounded_json_from_plain
from stateback.application.models import SubmitOperationRequest
from stateback.application.service import ApplicationService
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import EffectRef


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
