from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from stateback.application import ApplicationService
from stateback.application.auth import AuthenticatedIdentity
from stateback.application.models import SubmitOperationRequest
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.operation import Operation
from stateback.mcp import StatebackMcpTools, create_mcp_server
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
