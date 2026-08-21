from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from stateback.api import create_app
from stateback.application.auth import (
    AuthenticatedIdentity,
    Role,
    StaticTokenAuthenticator,
)
from stateback.application.service import (
    ApplicationService,
    ApplicationServiceError,
    OperationPage,
    OperationReconstruction,
)
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    OperationState,
    PrincipalType,
    RiskLevel,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import IntentEnvelope, operation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.semantic.models import SemanticStatus, empty_summary

pytestmark = [pytest.mark.contract, pytest.mark.unit]

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "test"
    / "contract-fixtures"
)


def _fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _operation() -> Operation:
    operation_id = OpaqueId(value="00000000-0000-4000-8000-000000000001")
    timestamp = UtcTimestamp(value=datetime(2026, 8, 20, 12, tzinfo=UTC))
    intent = IntentEnvelope.from_parts(
        effect=EffectRef(provider="github", action="create_issue", version="v1"),
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain(
            {"owner": "example", "repo": "sandbox", "title": "Fixture issue"}
        ),
        arguments_ref=None,
        requester=PrincipalRef(
            type=PrincipalType.AGENT,
            id="fixture-agent",
            display_name="Fixture Agent",
        ),
        requested_at=timestamp,
        metadata=(),
    )
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=operation_id,
        state=OperationState.READY,
        version=2,
        intent=intent,
        risk_level=RiskLevel.MODERATE,
        idempotency_identity=operation_idempotency_identity(operation_id),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_operation_page_fixture_matches_authoritative_serializer() -> None:
    wire = OperationPage(
        operations=(_operation(),), next_cursor="fixture-cursor"
    ).to_wire()
    assert _fixture("operation-list-v1.json") == wire


def test_empty_verification_reconstruction_matches_authoritative_serializer() -> None:
    wire = OperationReconstruction(
        operation=_operation(),
        policy_decisions=(),
        approvals=(),
        attempts=(),
        verifications=(),
        reconciliations=(),
        compensation=None,
        compensation_attempts=(),
        audit=(),
        available_actions=(),
    ).to_wire()
    assert _fixture("reconstruction-empty-verifications-v1.json") == wire


def test_verification_reconstruction_serializes_request_and_result_records() -> None:
    fixture = cast(dict[str, object], _fixture("reconstruction-verification-v1.json"))
    records = cast(list[dict[str, object]], fixture["verifications"])
    request = VerificationRequest.from_wire(records[0]["request"])
    result = VerificationResult.from_wire(records[0]["result"])
    wire = OperationReconstruction(
        operation=replace(_operation(), latest_verification_id=request.verification_id),
        policy_decisions=(),
        approvals=(),
        attempts=(),
        verifications=((request, result),),
        reconciliations=(),
        compensation=None,
        compensation_attempts=(),
        audit=(),
        available_actions=(),
    ).to_wire()
    assert wire == fixture


def test_semantic_unavailable_fixture_matches_authoritative_serializer() -> None:
    wire = empty_summary(
        status=SemanticStatus.UNAVAILABLE,
        reason_code="semantic_not_configured",
        operation=_operation(),
        audit=(),
        provider=None,
        model=None,
    ).to_wire()
    assert _fixture("semantic-unavailable-v1.json") == wire


def test_api_error_fixture_matches_http_producer() -> None:
    class StaleService:
        def search_operations(self, *_args: object) -> None:
            raise ApplicationServiceError("stale_version")

    identity = AuthenticatedIdentity(
        principal=PrincipalRef(
            type=PrincipalType.OPERATOR, id="fixture-operator", display_name=None
        ),
        roles=frozenset({Role.OPERATOR}),
    )
    client = TestClient(
        create_app(
            service=cast(ApplicationService, StaleService()),
            authenticator=StaticTokenAuthenticator(
                identities_by_token={"fixture-token": identity}
            ),
        )
    )
    response = client.get(
        "/v1/operator/operations",
        headers={"Authorization": "Bearer fixture-token"},
    )
    assert response.status_code == 409
    assert _fixture("error-v1.json") == response.json()
