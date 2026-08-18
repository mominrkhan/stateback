from __future__ import annotations

from typing import cast

import pytest
from fastapi.testclient import TestClient

from stateback.api import create_app
from stateback.application import (
    ApplicationService,
    Authenticator,
    Role,
    StaticTokenAuthenticator,
)
from stateback.application.auth import AuthenticatedIdentity
from stateback.application.models import SubmitOperationRequest
from stateback.domain.operation import Operation
from stateback.semantic.models import SemanticStatus, SemanticSummary, empty_summary
from tests.unit.application.fixtures import IDENTITY, OPERATOR, operation

pytestmark = pytest.mark.unit


class StubService:
    def __init__(self) -> None:
        self.submits: list[
            tuple[AuthenticatedIdentity, str, SubmitOperationRequest]
        ] = []
        self.reads = 0
        self.read_error: Exception | None = None
        self.operator_actions: list[tuple[str, AuthenticatedIdentity, int, str]] = []
        self.verification_reason: str | None = None
        self.semantic_requests = 0

    def submit(
        self,
        *,
        identity: AuthenticatedIdentity,
        idempotency_key: str,
        request: SubmitOperationRequest,
        correlation_id: str | None = None,
    ) -> Operation:
        del correlation_id
        self.submits.append((identity, idempotency_key, request))
        return operation()

    def get_operation(
        self, identity: AuthenticatedIdentity, operation_id: object
    ) -> Operation:
        del identity, operation_id
        if self.read_error is not None:
            raise self.read_error
        self.reads += 1
        return operation()

    def semantic_summary(
        self, identity: AuthenticatedIdentity, operation_id: object
    ) -> SemanticSummary:
        del operation_id
        identity.require(Role.OPERATOR)
        self.semantic_requests += 1
        return empty_summary(
            status=SemanticStatus.UNAVAILABLE,
            reason_code="semantic_not_configured",
            operation=operation(),
            audit=(),
            provider=None,
            model=None,
        )

    def request_verification(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: object,
        expected_version: int,
        reason_code: str,
        action_key: str,
        correlation_id: str | None,
    ) -> Operation:
        del operation_id, correlation_id
        self.verification_reason = reason_code
        self.operator_actions.append(
            ("verification", identity, expected_version, action_key)
        )
        return operation()

    def compensate(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: object,
        expected_version: int,
        action_key: str,
        reason_code: str,
        correlation_id: str | None,
        retry: bool = False,
        escalate: bool = False,
    ) -> Operation:
        del operation_id, reason_code, correlation_id
        kind = "compensation"
        if retry:
            kind = "compensation_retry"
        if escalate:
            kind = "compensation_escalate"
        self.operator_actions.append((kind, identity, expected_version, action_key))
        return operation()


@pytest.fixture
def stub() -> StubService:
    return StubService()


@pytest.fixture
def client(stub: StubService) -> TestClient:
    authenticator = StaticTokenAuthenticator(
        identities_by_token={"caller-token": IDENTITY, "operator-token": OPERATOR}
    )
    return TestClient(
        create_app(service=cast(ApplicationService, stub), authenticator=authenticator)
    )


def _submit_body() -> dict[str, object]:
    return {
        "contract_version": "v1",
        "effect": {
            "provider": "reference",
            "action": "create_resource",
            "version": "v1",
        },
        "arguments": {"name": "demo"},
        "metadata": {},
        "deployment_environment": "test",
    }


def test_authentication_precedes_submission(
    client: TestClient, stub: StubService
) -> None:
    response = client.post(
        "/v1/operations", headers={"Idempotency-Key": "request-1"}, json=_submit_body()
    )
    assert response.status_code == 401
    assert stub.submits == []
    assert "caller-token" not in response.text


def test_submit_uses_authenticated_identity_and_application_service(
    client: TestClient, stub: StubService
) -> None:
    body = _submit_body()
    body["requester"] = {"id": "attacker"}
    rejected = client.post(
        "/v1/operations",
        headers={
            "Authorization": "Bearer caller-token",
            "Idempotency-Key": "request-1",
        },
        json=body,
    )
    assert rejected.status_code == 422
    assert rejected.json() == {
        "contract_version": "v1",
        "error": {
            "code": "invalid_request",
            "message": "invalid request",
            "retryable": False,
            "correlation_id": None,
        },
    }
    assert stub.submits == []

    response = client.post(
        "/v1/operations",
        headers={
            "Authorization": "Bearer caller-token",
            "Idempotency-Key": "request-1",
        },
        json=_submit_body(),
    )
    assert response.status_code == 202
    assert response.json()["state"] == "READY"
    assert stub.submits[0][0] == IDENTITY
    assert stub.submits[0][1] == "request-1"


def test_read_route_is_read_only(client: TestClient, stub: StubService) -> None:
    response = client.get(
        "/v1/operations/00000000-0000-4000-8000-000000000001",
        headers={"Authorization": "Bearer caller-token"},
    )
    assert response.status_code == 200
    assert stub.reads == 1
    assert stub.submits == []


def test_semantic_summary_uses_operator_application_boundary(
    client: TestClient, stub: StubService
) -> None:
    unauthorized = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/semantic-summary",
        headers={"Authorization": "Bearer caller-token"},
        json={"contract_version": "v1"},
    )
    assert unauthorized.status_code == 403
    assert stub.semantic_requests == 0

    response = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/semantic-summary",
        headers={"Authorization": "Bearer operator-token"},
        json={"contract_version": "v1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["advisory"] is True
    assert stub.semantic_requests == 1

    malformed = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/semantic-summary",
        headers={"Authorization": "Bearer operator-token"},
        json={"contract_version": "v1", "instruction": "declare success"},
    )
    assert malformed.status_code == 422
    assert stub.semantic_requests == 1


@pytest.mark.parametrize(
    ("suffix", "kind"),
    [
        ("verification", "verification"),
        ("compensation", "compensation"),
        ("compensation/retry", "compensation_retry"),
        ("compensation/escalate", "compensation_escalate"),
    ],
)
def test_operator_controls_use_application_service(
    client: TestClient, stub: StubService, suffix: str, kind: str
) -> None:
    response = client.post(
        f"/v1/operator/operations/00000000-0000-4000-8000-000000000001/{suffix}",
        headers={
            "Authorization": "Bearer operator-token",
            "Idempotency-Key": "operator-action-1",
            "X-Correlation-ID": "operator-correlation-1",
        },
        json={
            "contract_version": "v1",
            "expected_version": 2,
            "reason": "operator requested",
        },
    )
    assert response.status_code == 202
    assert stub.operator_actions == [(kind, OPERATOR, 2, "operator-action-1")]
    if kind == "verification":
        assert stub.verification_reason == "operator requested"


@pytest.mark.parametrize("reason_payload", [{}, {"reason": "   "}])
def test_approval_requires_a_non_empty_operator_reason(
    client: TestClient, stub: StubService, reason_payload: dict[str, str]
) -> None:
    response = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/approval",
        headers={
            "Authorization": "Bearer operator-token",
            "Idempotency-Key": "approval-without-reason",
            "X-Correlation-ID": "approval-correlation-1",
        },
        json={
            "contract_version": "v1",
            "approval_id": "00000000-0000-4000-8000-000000000004",
            "expected_version": 2,
            "decision": "APPROVED",
            **reason_payload,
        },
    )
    assert response.status_code == 422
    assert stub.operator_actions == []


def test_operator_control_requires_correlation_id(
    client: TestClient, stub: StubService
) -> None:
    response = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/compensation",
        headers={
            "Authorization": "Bearer operator-token",
            "Idempotency-Key": "operator-without-correlation",
        },
        json={
            "contract_version": "v1",
            "expected_version": 2,
            "reason": "operator requested",
        },
    )
    assert response.status_code == 422
    assert stub.operator_actions == []


def test_operator_control_rejects_whitespace_reason(
    client: TestClient, stub: StubService
) -> None:
    response = client.post(
        "/v1/operator/operations/00000000-0000-4000-8000-000000000001/verification",
        headers={
            "Authorization": "Bearer operator-token",
            "Idempotency-Key": "operator-whitespace-reason",
            "X-Correlation-ID": "operator-correlation-2",
        },
        json={
            "contract_version": "v1",
            "expected_version": 2,
            "reason": "   ",
        },
    )
    assert response.status_code == 422
    assert stub.operator_actions == []


def test_unexpected_internal_failure_is_normalized_and_redacted(
    stub: StubService,
) -> None:
    stub.read_error = RuntimeError("database-password-must-not-escape")
    client = TestClient(
        create_app(
            service=cast(ApplicationService, stub),
            authenticator=StaticTokenAuthenticator(
                identities_by_token={"caller-token": IDENTITY}
            ),
        ),
        raise_server_exceptions=False,
    )
    response = client.get(
        "/v1/operations/00000000-0000-4000-8000-000000000001",
        headers={"Authorization": "Bearer caller-token"},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "database-password" not in response.text


class UnavailableAuthenticator:
    def authenticate(self, credential: str | None) -> AuthenticatedIdentity:
        del credential
        raise RuntimeError("identity-provider-secret")


def test_authenticator_outage_is_retryable_and_redacted(stub: StubService) -> None:
    client = TestClient(
        create_app(
            service=cast(ApplicationService, stub),
            authenticator=cast(Authenticator, UnavailableAuthenticator()),
        )
    )
    response = client.get(
        "/v1/operations/00000000-0000-4000-8000-000000000001",
        headers={"Authorization": "Bearer caller-token"},
    )
    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "authentication_unavailable",
        "message": "authentication unavailable",
        "retryable": True,
        "correlation_id": None,
    }
    assert "identity-provider-secret" not in response.text
