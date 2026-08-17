from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from stateback.api import create_app
from stateback.application import (
    ApplicationService,
    ApplicationServiceError,
    AuthenticatedIdentity,
    AuthorizationError,
    Role,
    StaticTokenAuthenticator,
)
from stateback.application.models import OperationSearch, SubmitOperationRequest
from stateback.approval import ApprovalService, ConfiguredApproverAuthorizer
from stateback.compensation import CompensationService
from stateback.domain.enums import (
    ApprovalState,
    OperationState,
    PolicyVerdict,
    PrincipalType,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.policy import PolicyObligations
from stateback.domain.refs import PrincipalRef
from stateback.mcp import StatebackMcpTools
from stateback.policy import PHASE5_DEFAULT_OBLIGATIONS, PolicyRule, RulePolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_NONE
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SynchronousRuntime
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import IdSeq, execute_ids
from tests.unit.domain.fixtures import REQUESTER
from tests.unit.runtime.fixtures import ARGUMENTS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]

CALLER = AuthenticatedIdentity(
    principal=REQUESTER,
    roles=frozenset({Role.CALLER}),
)
OPERATOR = AuthenticatedIdentity(
    principal=PrincipalRef(
        type=PrincipalType.OPERATOR, id="operator-1", display_name=None
    ),
    roles=frozenset({Role.READER, Role.OPERATOR, Role.APPROVER}),
)


def _request() -> SubmitOperationRequest:
    from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY

    return SubmitOperationRequest(
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        arguments=ARGUMENTS,
        metadata=(),
        deployment_environment="test",
    )


def test_public_idempotency_status_audit_and_operator_reconstruction(
    uow_factory: sessionmaker[Session], runtime: SynchronousRuntime
) -> None:
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    first = service.submit(
        identity=CALLER, idempotency_key="request-1", request=_request()
    )
    repeated = service.submit(
        identity=CALLER, idempotency_key="request-1", request=_request()
    )
    assert repeated.operation_id == first.operation_id
    assert repeated.intent.intent_digest == first.intent.intent_digest

    loaded = service.get_operation(CALLER, first.operation_id)
    assert loaded == repeated
    audit = service.audit_page(
        identity=CALLER, operation_id=first.operation_id, limit=1
    )
    assert len(audit.events) == 1
    assert audit.next_after_sequence == 1

    page = service.search_operations(OPERATOR, OperationSearch(limit=10))
    assert [item.operation_id for item in page.operations] == [first.operation_id]
    reconstruction = service.reconstruct(OPERATOR, first.operation_id)
    assert reconstruction.operation == first
    assert reconstruction.policy_decisions
    assert reconstruction.audit


def test_idempotency_conflict_and_cross_caller_read_denied(
    uow_factory: sessionmaker[Session], runtime: SynchronousRuntime
) -> None:
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    operation = service.submit(
        identity=CALLER, idempotency_key="request-1", request=_request()
    )
    conflicting = SubmitOperationRequest(
        effect=_request().effect,
        arguments=json_from_plain({"resource_id": "different"}),
        metadata=(),
        deployment_environment="test",
    )
    with pytest.raises(ApplicationServiceError, match="idempotency_conflict"):
        service.submit(
            identity=CALLER,
            idempotency_key="request-1",
            request=conflicting,
        )
    stranger = AuthenticatedIdentity(
        principal=PrincipalRef(
            type=PrincipalType.AGENT, id="agent-2", display_name=None
        ),
        roles=frozenset({Role.CALLER}),
    )
    with pytest.raises(AuthorizationError, match="operation_read_forbidden"):
        service.get_operation(stranger, operation.operation_id)
    reader = AuthenticatedIdentity(
        principal=stranger.principal,
        roles=frozenset({Role.READER}),
    )
    with pytest.raises(AuthorizationError, match="operation_read_forbidden"):
        service.get_operation(reader, operation.operation_id)


def test_http_api_end_to_end_uses_same_service_and_operator_boundary(
    uow_factory: sessionmaker[Session], runtime: SynchronousRuntime
) -> None:
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    client = TestClient(
        create_app(
            service=service,
            authenticator=StaticTokenAuthenticator(
                identities_by_token={"caller-token": CALLER, "operator-token": OPERATOR}
            ),
        )
    )
    effect = _request().effect
    submitted = client.post(
        "/v1/operations",
        headers={
            "Authorization": "Bearer caller-token",
            "Idempotency-Key": "request-1",
        },
        json={
            "contract_version": "v1",
            "effect": effect.to_wire(),
            "arguments": {"resource_id": "res-1"},
            "metadata": {},
            "deployment_environment": "test",
        },
    )
    assert submitted.status_code == 202
    payload = submitted.json()
    operation_id = payload["operation_id"]
    assert payload["state"] == "READY"

    status = client.get(
        f"/v1/operations/{operation_id}",
        headers={"Authorization": "Bearer caller-token"},
    )
    assert status.status_code == 200
    assert status.json()["operation_id"] == operation_id
    audit = client.get(
        f"/v1/operations/{operation_id}/audit?limit=1",
        headers={"Authorization": "Bearer caller-token"},
    )
    assert audit.status_code == 200
    assert len(audit.json()["items"]) == 1
    assert audit.json()["next_after_sequence"] == 1
    reconstructed = client.get(
        f"/v1/operator/operations/{operation_id}",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert reconstructed.status_code == 200
    assert reconstructed.json()["operation"]["state"] == "READY"
    assert reconstructed.json()["audit"]


@pytest.mark.parametrize(
    ("verdict", "expected_state"),
    [
        (PolicyVerdict.DENY, OperationState.DENIED),
        (PolicyVerdict.REQUIRE_APPROVAL, OperationState.AWAITING_APPROVAL),
    ],
)
def test_public_submission_preserves_policy_disposition(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    verdict: PolicyVerdict,
    expected_state: OperationState,
) -> None:
    obligations: PolicyObligations = PHASE5_DEFAULT_OBLIGATIONS
    policy = RulePolicyEngine(
        policy_revision="public-policy-v1",
        rules=(
            PolicyRule(
                rule_id="public-rule",
                verdict=verdict,
                obligations=obligations,
                providers=frozenset({_request().effect.provider}),
            ),
        ),
        default_obligations=obligations,
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=policy)
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    operation = service.submit(
        identity=CALLER,
        idempotency_key=f"policy-{verdict.value}",
        request=_request(),
    )
    assert operation.state is expected_state


def test_mcp_uses_real_application_boundary_and_enforces_role(
    uow_factory: sessionmaker[Session], runtime: SynchronousRuntime
) -> None:
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    tools = StatebackMcpTools(service=service, identity=CALLER)
    result = tools.submit(
        {
            "provider": _request().effect.provider,
            "action": _request().effect.action,
            "effect_version": _request().effect.version,
            "arguments": {"resource_id": "mcp-resource"},
            "idempotency_key": "mcp-request-1",
            "deployment_environment": "test",
        }
    )
    assert result["state"] == "READY"

    reader_only = AuthenticatedIdentity(
        principal=OPERATOR.principal,
        roles=frozenset({Role.READER}),
    )
    unauthorized = StatebackMcpTools(service=service, identity=reader_only)
    with pytest.raises(AuthorizationError, match="insufficient_role"):
        unauthorized.submit(
            {
                "provider": _request().effect.provider,
                "action": _request().effect.action,
                "effect_version": _request().effect.version,
                "arguments": {"resource_id": "blocked"},
                "idempotency_key": "mcp-request-blocked",
                "deployment_environment": "test",
            }
        )


def test_operator_search_cursor_is_stable_and_non_overlapping(
    uow_factory: sessionmaker[Session], runtime: SynchronousRuntime
) -> None:
    service = ApplicationService(session_factory=uow_factory, runtime=runtime)
    created = {
        service.submit(
            identity=CALLER,
            idempotency_key=f"page-{index}",
            request=_request(),
        ).operation_id
        for index in range(3)
    }
    first = service.search_operations(
        OPERATOR,
        OperationSearch(
            state=OperationState.READY.value,
            provider=_request().effect.provider,
            limit=2,
        ),
    )
    assert len(first.operations) == 2
    assert first.next_cursor is not None
    second = service.search_operations(
        OPERATOR,
        OperationSearch(cursor=first.next_cursor, limit=2),
    )
    assert len(second.operations) == 1
    assert second.next_cursor is None
    observed = {item.operation_id for item in first.operations + second.operations}
    assert observed == created


def test_operator_approval_is_authorized_bound_and_idempotent(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> None:
    obligations = PHASE5_DEFAULT_OBLIGATIONS
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        policy_engine=RulePolicyEngine(
            policy_revision="approval-public-v1",
            rules=(
                PolicyRule(
                    rule_id="approval-public",
                    verdict=PolicyVerdict.REQUIRE_APPROVAL,
                    obligations=obligations,
                    providers=frozenset({_request().effect.provider}),
                ),
            ),
            default_obligations=obligations,
        ),
    )
    approvals = ApprovalService(
        session_factory=uow_factory,
        authorizer=ConfiguredApproverAuthorizer(
            allowed_principals=frozenset(
                {(OPERATOR.principal.type, OPERATOR.principal.id)}
            )
        ),
        clock=clock,
    )
    service = ApplicationService(
        session_factory=uow_factory,
        runtime=runtime,
        approvals=approvals,
        registry=registry,
    )
    awaiting = service.submit(
        identity=CALLER,
        idempotency_key="approval-request",
        request=_request(),
    )
    assert awaiting.state is OperationState.AWAITING_APPROVAL
    assert awaiting.current_approval_id is not None
    assert service.reconstruct(OPERATOR, awaiting.operation_id).available_actions == (
        "approve",
        "reject",
    )
    operator_without_approval = AuthenticatedIdentity(
        principal=OPERATOR.principal,
        roles=frozenset({Role.OPERATOR}),
    )
    assert (
        service.reconstruct(
            operator_without_approval, awaiting.operation_id
        ).available_actions
        == ()
    )
    approved = service.decide_approval(
        identity=OPERATOR,
        operation_id=awaiting.operation_id,
        approval_id=awaiting.current_approval_id,
        expected_version=awaiting.version,
        decision=ApprovalState.APPROVED,
        reason="reviewed",
        action_key="approval-action",
        correlation_id="approval-correlation",
    )
    assert approved.state is OperationState.READY
    repeated = service.decide_approval(
        identity=OPERATOR,
        operation_id=awaiting.operation_id,
        approval_id=awaiting.current_approval_id,
        expected_version=awaiting.version,
        decision=ApprovalState.APPROVED,
        reason="reviewed",
        action_key="approval-action",
        correlation_id="approval-correlation",
    )
    assert repeated == approved
    reconstruction = service.reconstruct(OPERATOR, awaiting.operation_id)
    decided_approval = reconstruction.approvals[-1]
    assert decided_approval.decided_by == OPERATOR.principal
    assert decided_approval.reason == "reviewed"
    assert any(
        event.actor == OPERATOR.principal
        and event.event_type.value == "approval.decided.v1"
        for event in reconstruction.audit
    )

    via_http = service.submit(
        identity=CALLER,
        idempotency_key="approval-http-request",
        request=_request(),
    )
    assert via_http.current_approval_id is not None
    client = TestClient(
        create_app(
            service=service,
            authenticator=StaticTokenAuthenticator(
                identities_by_token={"operator-token": OPERATOR}
            ),
        )
    )
    response = client.post(
        f"/v1/operator/operations/{via_http.operation_id}/approval",
        headers={
            "Authorization": "Bearer operator-token",
            "Idempotency-Key": "approval-http-action",
            "X-Correlation-ID": "approval-http-correlation",
        },
        json={
            "contract_version": "v1",
            "approval_id": str(via_http.current_approval_id),
            "expected_version": via_http.version,
            "decision": "APPROVED",
            "reason": "reviewed through API",
        },
    )
    assert response.status_code == 202
    assert response.json()["state"] == "READY"


def test_operator_compensation_seam_enforces_eligibility_and_audits_reason(
    uow_factory: sessionmaker[Session],
    runtime: SynchronousRuntime,
    registry: CapabilityRegistry,
    clock: FixedClock,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    service = ApplicationService(
        session_factory=uow_factory,
        runtime=runtime,
        compensation=compensation,
        registry=registry,
    )
    succeeded = runtime.run(make_submit(seq), execute_ids(seq)).operation
    assert succeeded is not None
    assert succeeded.state is OperationState.SUCCEEDED
    assert service.reconstruct(OPERATOR, succeeded.operation_id).available_actions == (
        "compensate",
    )
    started = service.compensate(
        identity=OPERATOR,
        operation_id=succeeded.operation_id,
        expected_version=succeeded.version,
        action_key="operator-compensation",
        reason_code="customer_remediation",
        correlation_id="operator-correlation",
    )
    assert started.state is OperationState.COMPENSATING
    reconstruction = service.reconstruct(OPERATOR, succeeded.operation_id)
    assert any(
        event.actor == OPERATOR.principal
        and event.reason_code == "customer_remediation"
        for event in reconstruction.audit
    )

    ready = service.submit(
        identity=CALLER, idempotency_key="illegal-compensation", request=_request()
    )
    assert (
        "compensate"
        not in service.reconstruct(OPERATOR, ready.operation_id).available_actions
    )
    with pytest.raises(ApplicationServiceError, match="source_state_mismatch"):
        service.compensate(
            identity=OPERATOR,
            operation_id=ready.operation_id,
            expected_version=ready.version,
            action_key="illegal-operator-compensation",
            reason_code="not_eligible",
            correlation_id="illegal-compensation-correlation",
        )

    unsupported = runtime.run(
        make_submit(
            seq,
            effect=EFFECT_MUTATE_NONE,
            arguments=json_from_plain({"resource_id": "unsupported-resource"}),
        ),
        execute_ids(seq),
    ).operation
    assert unsupported is not None
    assert (
        "compensate"
        not in service.reconstruct(OPERATOR, unsupported.operation_id).available_actions
    )

    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_VALIDATION)
    failed_without_artifact = runtime.run(
        make_submit(
            seq,
            arguments=json_from_plain({"resource_id": "failed-resource"}),
        ),
        execute_ids(seq),
    ).operation
    assert failed_without_artifact is not None
    assert failed_without_artifact.state is OperationState.FAILED
    assert (
        "compensate"
        not in service.reconstruct(
            OPERATOR, failed_without_artifact.operation_id
        ).available_actions
    )
