from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from stateback.application import ApplicationService
from stateback.application.auth import AuthenticatedIdentity
from stateback.application.models import SubmitOperationRequest
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.operation import Operation
from stateback.mcp import (
    ApiMcpTools,
    StatebackMcpTools,
    create_api_mcp_server,
    create_mcp_server,
)
from stateback.sdk import StatebackClient, StatebackTransportError
from tests.unit.application.fixtures import IDENTITY, operation

pytestmark = [pytest.mark.unit, pytest.mark.benchmark_correctness]


class StubService:
    def __init__(self) -> None:
        self.submitted: SubmitOperationRequest | None = None
        self.identity: AuthenticatedIdentity | None = None
        self.read_operation = operation()
        self.reads: list[str] = []

    def submit(
        self,
        *,
        identity: AuthenticatedIdentity,
        idempotency_key: str,
        request: SubmitOperationRequest,
        correlation_id: str | None = None,
    ) -> Operation:
        del idempotency_key, correlation_id
        self.identity = identity
        self.submitted = request
        return operation()

    def get_operation(
        self, identity: AuthenticatedIdentity, operation_id: object
    ) -> Operation:
        self.identity = identity
        self.reads.append(str(operation_id))
        return self.read_operation

    def audit_page(self, **kwargs: object) -> object:
        self.identity = cast(AuthenticatedIdentity, kwargs["identity"])
        self.reads.append(str(kwargs["operation_id"]))

        class Page:
            def to_wire(self) -> dict[str, object]:
                return {
                    "contract_version": "v1",
                    "items": [],
                    "next_after_sequence": None,
                }

        return Page()


def test_mutation_uses_application_service_identity() -> None:
    stub = StubService()
    tools = StatebackMcpTools(service=cast(ApplicationService, stub), identity=IDENTITY)
    result = tools.submit(
        {
            "provider": "reference",
            "action": "create_resource",
            "effect_version": "v1",
            "arguments": {"name": "demo"},
            "idempotency_key": "request-1",
            "deployment_environment": "test",
        }
    )
    assert result["operation_id"] == str(operation().operation_id)
    assert stub.identity == IDENTITY
    assert stub.submitted is not None


def test_malicious_escape_hatch_argument_is_rejected() -> None:
    tools = StatebackMcpTools(
        service=cast(ApplicationService, StubService()), identity=IDENTITY
    )
    with pytest.raises(ValidationError):
        tools.submit(
            {
                "provider": "reference",
                "action": "create_resource",
                "effect_version": "v1",
                "arguments": {},
                "idempotency_key": "request-1",
                "deployment_environment": "test",
                "provider_url": "https://attacker.invalid",
                "shell": "rm -rf /",
            }
        )


def test_oversize_mcp_argument_is_rejected_before_submission() -> None:
    stub = StubService()
    tools = StatebackMcpTools(service=cast(ApplicationService, stub), identity=IDENTITY)
    with pytest.raises(ContractValidationError, match="supported length"):
        tools.submit(
            {
                "provider": "reference",
                "action": "create_resource",
                "effect_version": "v1",
                "arguments": {"value": "x" * 65_537},
                "idempotency_key": "request-1",
                "deployment_environment": "test",
            }
        )
    assert stub.submitted is None


def test_mcp_server_exposes_only_bounded_tools() -> None:
    server = create_mcp_server(
        service=cast(ApplicationService, StubService()), identity=IDENTITY
    )
    assert server.name == "stateback"


def test_status_and_audit_are_read_only_application_calls() -> None:
    stub = StubService()
    tools = StatebackMcpTools(service=cast(ApplicationService, stub), identity=IDENTITY)
    operation_id = str(operation().operation_id)
    assert tools.status(operation_id)["state"] == "READY"
    assert tools.audit(operation_id)["items"] == []
    assert stub.submitted is None
    assert stub.reads == [operation_id, operation_id]


@pytest.mark.parametrize("state", ["UNKNOWN", "VERIFYING", "MANUAL_INTERVENTION"])
def test_status_preserves_asynchronous_and_unknown_states(state: str) -> None:
    from stateback.domain.enums import OperationState

    stub = StubService()
    stub.read_operation = operation(OperationState(state))
    tools = StatebackMcpTools(service=cast(ApplicationService, stub), identity=IDENTITY)
    assert tools.status(str(operation().operation_id))["state"] == state


def test_mcp_source_has_no_provider_or_shell_bypass() -> None:
    source = (
        Path(__file__).resolve().parents[3] / "src" / "stateback" / "mcp" / "server.py"
    ).read_text(encoding="utf-8")
    assert "stateback.providers" not in source
    assert "subprocess" not in source
    assert "os.system" not in source


def test_api_mcp_server_exposes_typed_v01_workflow_tools() -> None:
    server = create_api_mcp_server(cast(StatebackClient, object()))
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {
        "stateback_github_create_issue",
        "stateback_github_create_issue_comment",
        "stateback_github_add_label",
        "stateback_github_create_pull_request",
        "stateback_github_merge_pull_request",
        "stateback_operation_status",
        "stateback_operation_audit",
    }
    merge = next(
        tool for tool in tools if tool.name == "stateback_github_merge_pull_request"
    )
    assert "approval-gated" in (merge.description or "")
    assert "idempotency_key" in merge.input_schema["required"]
    assert merge.input_schema["properties"]["idempotency_key"]["minLength"] == 1
    assert merge.input_schema["properties"]["idempotency_key"]["maxLength"] == 200
    assert merge.input_schema["properties"]["pull_number"]["exclusiveMinimum"] == 0
    assert merge.input_schema["properties"]["head_sha"]["pattern"] == (
        "^[0-9a-fA-F]{40}$"
    )
    assert merge.input_schema["properties"]["merge_method"]["enum"] == [
        "merge",
        "squash",
        "rebase",
    ]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "stateback_github_create_issue_comment",
            {
                "owner": "acme",
                "repo": "sandbox",
                "issue_number": 0,
                "body": "note",
                "idempotency_key": "comment-0",
            },
        ),
        (
            "stateback_github_merge_pull_request",
            {
                "owner": "acme",
                "repo": "sandbox",
                "pull_number": 17,
                "head_sha": "not-a-sha",
                "idempotency_key": "merge-bad-sha",
            },
        ),
        (
            "stateback_github_merge_pull_request",
            {
                "owner": "acme",
                "repo": "sandbox",
                "pull_number": 17,
                "head_sha": "a" * 40,
                "merge_method": "force",
                "idempotency_key": "merge-bad-method",
            },
        ),
    ],
)
def test_api_mcp_rejects_invalid_provider_arguments_before_api_submission(
    tool_name: str, arguments: dict[str, object]
) -> None:
    class NoSubmissionClient:
        def submit(self, **_kwargs: object) -> object:
            raise AssertionError("invalid MCP input reached API submission")

    server = create_api_mcp_server(cast(StatebackClient, NoSubmissionClient()))
    with pytest.raises(ToolError, match="validation error"):
        asyncio.run(server.call_tool(tool_name, arguments))


def _api_response(payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(payload).encode())


def test_api_mcp_execution_reports_canonical_approval_state_and_payload() -> None:
    seen: list[httpx.Request] = []
    payload = operation().to_wire()
    payload["state"] = "AWAITING_APPROVAL"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _api_response(payload, 202)

    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(handler),
    )
    tools = ApiMcpTools(client)
    result = tools.submit_github(
        "merge_pull_request",
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
            "merge_method": "squash",
        },
        "merge-17",
    )
    assert result["state"] == "AWAITING_APPROVAL"
    assert result["provider_outcome"] == "NOT_ESTABLISHED"
    submitted = json.loads(seen[0].content)
    assert submitted["effect"] == {
        "provider": "github",
        "action": "merge_pull_request",
        "version": "v1",
    }
    assert "approval" not in submitted and "execute" not in submitted
    client.close()


def test_api_mcp_status_and_audit_preserve_unknown_and_ordered_evidence() -> None:
    operation_payload = operation().to_wire()
    operation_payload["state"] = "UNKNOWN"
    audit_payload = {
        "contract_version": "v1",
        "items": [{"sequence": 1, "event_type": "EXECUTION_UNKNOWN"}],
        "next_after_sequence": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _api_response(
            audit_payload if request.url.path.endswith("/audit") else operation_payload
        )

    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(handler),
    )
    tools = ApiMcpTools(client)
    operation_id = str(operation().operation_id)
    assert tools.status(operation_id)["state"] == "UNKNOWN"
    assert tools.audit(operation_id)["items"] == audit_payload["items"]
    client.close()


def test_api_mcp_transport_failure_is_not_reported_as_operation_state() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    client = StatebackClient(
        base_url="https://stateback.test",
        token="safe-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(StatebackTransportError, match="transport_failed"):
        ApiMcpTools(client).submit_github(
            "add_label",
            {
                "owner": "acme",
                "repo": "sandbox",
                "issue_number": 42,
                "label": "safe",
            },
            "label-42",
        )
    client.close()
