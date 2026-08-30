from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.approval import (
    ApprovalDecisionCommand,
    ApprovalDecisionIds,
    ApprovalDisposition,
    ApprovalService,
    ConfiguredApproverAuthorizer,
)
from stateback.compensation.service import CompensationService
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    OperationState,
    PolicyVerdict,
    PrincipalType,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.messaging import OutboxEvent, WorkMessageV1
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.messaging.codec import encode_work_message
from stateback.messaging.worker import AckDecision, WorkHandler
from stateback.persistence.uow import unit_of_work
from stateback.policy import PHASE5_DEFAULT_OBLIGATIONS, PolicyRule, RulePolicyEngine
from stateback.providers.github import (
    EFFECT_ADD_LABEL,
    EFFECT_CREATE_ISSUE,
    EFFECT_CREATE_ISSUE_COMMENT,
    EFFECT_CREATE_PULL_REQUEST,
    EFFECT_MERGE_PULL_REQUEST,
    GitHubAdapter,
    GitHubHttpResponse,
)
from stateback.providers.github.demo_fault import OperationScopedLostResponseAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SimulatedCrash, SynchronousRuntime
from stateback.runtime.faults import RuntimeCrashPoint
from tests.integration.recovery.conftest import make_recovery
from tests.integration.runtime.conftest import (
    load_attempts,
    load_operation,
    make_submit,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

APPROVER = PrincipalRef(
    type=PrincipalType.HUMAN,
    id="github-approver",
    display_name=None,
)


class ScriptedGitHub:
    def __init__(self) -> None:
        self.responses: list[GitHubHttpResponse | Exception] = []
        self.requests: list[tuple[str, str, bytes | None]] = []

    def enqueue(self, value: GitHubHttpResponse | Exception) -> None:
        self.responses.append(value)

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
    ) -> GitHubHttpResponse:
        del timeout_seconds
        self.requests.append((method, path, body))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def github_response(
    status: int, body: object, request_id: str = "github-request-1"
) -> GitHubHttpResponse:
    return GitHubHttpResponse(
        status=status,
        headers=(("x-github-request-id", request_id),),
        body=json.dumps(body).encode("utf-8"),
    )


def github_issue(operation_id: OpaqueId) -> dict[str, object]:
    return {
        "id": 7001,
        "number": 17,
        "html_url": "https://github.com/acme/sandbox/issues/17",
        "repository_url": "https://api.github.com/repos/acme/sandbox",
        "state": "open",
        "body": f"<!-- stateback-operation:{operation_id.value} -->",
    }


def policy(verdict: PolicyVerdict) -> RulePolicyEngine:
    return RulePolicyEngine(
        policy_revision=f"github-policy-{verdict.value.lower()}-v1",
        rules=(
            PolicyRule(
                rule_id=f"github-{verdict.value.lower()}",
                verdict=verdict,
                obligations=PHASE5_DEFAULT_OBLIGATIONS,
                providers=frozenset({"github"}),
            ),
        ),
        default_obligations=PHASE5_DEFAULT_OBLIGATIONS,
    )


def runtime_services(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    transport: ScriptedGitHub,
    verdict: PolicyVerdict,
    demo_arm_directory: Path | None = None,
    crash_after: RuntimeCrashPoint | None = None,
) -> tuple[
    SynchronousRuntime,
    CapabilityRegistry,
    RecoveryService,
    CompensationService,
]:
    registry = CapabilityRegistry()
    github = GitHubAdapter(transport=transport, clock=clock)
    registry.register(
        github
        if demo_arm_directory is None
        else OperationScopedLostResponseAdapter(
            delegate=github, arm_directory=demo_arm_directory, clock=clock
        )
    )
    runtime = SynchronousRuntime(
        session_factory=uow_factory,
        registry=registry,
        policy_engine=policy(verdict),
        clock=clock,
        crash_after=crash_after,
    )
    return (
        runtime,
        registry,
        RecoveryService(session_factory=uow_factory, registry=registry, clock=clock),
        CompensationService(
            session_factory=uow_factory, registry=registry, clock=clock
        ),
    )


def github_submit(seq: IdSeq, operation_id: OpaqueId) -> object:
    ids = submit_ids(seq, operation_id=operation_id)
    return make_submit(
        seq,
        ids=ids,
        effect=EFFECT_CREATE_ISSUE,
        arguments=json_from_plain(
            {
                "owner": "acme",
                "repo": "sandbox",
                "title": "Production seam proof",
                "body": "Stateback runtime integration",
            }
        ),
    )


def github_effect_submit(
    seq: IdSeq,
    operation_id: OpaqueId,
    *,
    effect: EffectRef,
    arguments: dict[str, object],
) -> object:
    ids = submit_ids(seq, operation_id=operation_id)
    return make_submit(
        seq,
        ids=ids,
        effect=effect,
        arguments=json_from_plain(arguments),
    )


def github_comment(operation_id: OpaqueId) -> dict[str, object]:
    return {
        "id": 81,
        "html_url": "https://github.com/acme/sandbox/issues/42#issuecomment-81",
        "issue_url": "https://api.github.com/repos/acme/sandbox/issues/42",
        "body": f"note\n\n<!-- stateback-operation:{operation_id.value} -->",
    }


def github_pull(operation_id: OpaqueId, *, merged: bool = False) -> dict[str, object]:
    return {
        "id": 7002,
        "number": 17,
        "html_url": "https://github.com/acme/sandbox/pull/17",
        "state": "closed" if merged else "open",
        "body": f"<!-- stateback-operation:{operation_id.value} -->",
        "head": {
            "sha": "a" * 40,
            "ref": "feature",
            "label": "acme:feature",
            "repo": {"full_name": "acme/sandbox"},
        },
        "base": {"ref": "main", "repo": {"full_name": "acme/sandbox"}},
        "merged": merged,
    }


def work_message(seq: IdSeq, event: OutboxEvent) -> bytes:
    return encode_work_message(
        WorkMessageV1(
            contract_version=CONTRACT_VERSION,
            message_id=seq.next(),
            outbox_event_id=event.event_id,
            operation_id=event.aggregate_id,
            expected_operation_version=event.operation_version,
            command=event.command,
            correlation_id=event.correlation_id,
            created_at=event.created_at,
        )
    )


def pending(
    uow_factory: sessionmaker[Session],
    operation_id: OpaqueId,
    command: WorkCommand,
) -> OutboxEvent:
    with unit_of_work(uow_factory) as uow:
        matches = [
            event
            for event in uow.outbox_events.list_pending_for_claim(100)
            if event.aggregate_id == operation_id and event.command is command
        ]
    return matches[-1]


def test_github_approval_then_distributed_execution_persists_external_ids(
    uow_factory: sessionmaker[Session], clock: FixedClock, seq: IdSeq
) -> None:
    transport = ScriptedGitHub()
    operation_id = seq.next()
    transport.enqueue(github_response(201, github_issue(operation_id)))
    runtime, registry, recovery, compensation = runtime_services(
        uow_factory, clock, transport, PolicyVerdict.REQUIRE_APPROVAL
    )
    submit = github_submit(seq, operation_id)
    from stateback.runtime.commands import SubmitCommand

    assert isinstance(submit, SubmitCommand)
    submitted = runtime.submit(submit)
    assert submitted.operation is not None
    approval_id = submit.ids.approval_id
    service = ApprovalService(
        session_factory=uow_factory,
        authorizer=ConfiguredApproverAuthorizer(
            allowed_principals=frozenset({(APPROVER.type, APPROVER.id)})
        ),
        clock=clock,
    )
    granted = service.decide(
        ApprovalDecisionCommand(
            operation_id=operation_id,
            approval_id=approval_id,
            expected_version=submitted.operation.version,
            decision=ApprovalState.APPROVED,
            actor=APPROVER,
            reason="approved GitHub issue creation",
            correlation_id="github-seam",
            ids=ApprovalDecisionIds(
                transition_audit_event_id=seq.next(),
                approval_audit_event_id=seq.next(),
                outbox_event_id=seq.next(),
            ),
        )
    )
    assert granted.disposition is ApprovalDisposition.ACCEPTED
    event = pending(uow_factory, operation_id, WorkCommand.EXECUTE)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    payload = work_message(seq, event)
    assert handler.handle(payload, delivery_count=1) is AckDecision.ACK
    assert handler.handle(payload, delivery_count=2) is AckDecision.ACK
    assert load_operation(uow_factory, operation_id).state is OperationState.SUCCEEDED
    attempts = load_attempts(uow_factory, operation_id)
    assert len(attempts) == 1
    assert attempts[0].external_operation_id == "github:issue:7001"
    assert attempts[0].external_resource_ids == ("acme/sandbox#17",)
    assert len(transport.requests) == 1


def test_github_scoped_lost_response_verifies_without_reexecution(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
    tmp_path: Path,
) -> None:
    transport = ScriptedGitHub()
    operation_id = seq.next()
    (tmp_path / operation_id.value).write_text("armed\n")
    transport.enqueue(github_response(201, github_issue(operation_id)))
    transport.enqueue(github_response(200, {"items": [github_issue(operation_id)]}))
    runtime, _, recovery, compensation = runtime_services(
        uow_factory,
        clock,
        transport,
        PolicyVerdict.ALLOW,
        demo_arm_directory=tmp_path,
    )
    submit = github_submit(seq, operation_id)
    from stateback.runtime.commands import SubmitCommand

    assert isinstance(submit, SubmitCommand)
    submitted = runtime.submit(submit)
    assert submitted.operation is not None
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    execute_event = pending(uow_factory, operation_id, WorkCommand.EXECUTE)
    assert (
        handler.handle(work_message(seq, execute_event), delivery_count=1)
        is AckDecision.ACK
    )
    assert load_operation(uow_factory, operation_id).state is OperationState.UNKNOWN
    verify_event = pending(uow_factory, operation_id, WorkCommand.VERIFY)
    assert (
        handler.handle(work_message(seq, verify_event), delivery_count=1)
        is AckDecision.ACK
    )
    assert load_operation(uow_factory, operation_id).state is OperationState.SUCCEEDED
    assert [request[0] for request in transport.requests] == ["POST", "GET"]
    assert len(load_attempts(uow_factory, operation_id)) == 1
    assert not (tmp_path / operation_id.value).exists()


@pytest.mark.parametrize(
    ("effect", "arguments", "expected_targets"),
    [
        (
            EFFECT_CREATE_ISSUE_COMMENT,
            {
                "owner": "acme",
                "repo": "sandbox",
                "issue_number": 42,
                "body": "note",
            },
            ("github:issue-target:acme/sandbox#42",),
        ),
        (
            EFFECT_ADD_LABEL,
            {
                "owner": "acme",
                "repo": "sandbox",
                "issue_number": 42,
                "label": "safe",
            },
            ("github:issue-target:acme/sandbox#42", "github:label:safe"),
        ),
        (
            EFFECT_CREATE_PULL_REQUEST,
            {
                "owner": "acme",
                "repo": "sandbox",
                "head": "feature",
                "base": "main",
                "title": "Safe change",
            },
            (
                "github:repository:acme/sandbox",
                "github:head-ref:feature",
                "github:base-ref:main",
            ),
        ),
        (
            EFFECT_MERGE_PULL_REQUEST,
            {
                "owner": "acme",
                "repo": "sandbox",
                "pull_number": 17,
                "head_sha": "a" * 40,
                "merge_method": "squash",
            },
            ("github:pull:acme/sandbox#17", f"github:head-sha:{'a' * 40}"),
        ),
    ],
)
def test_new_github_effect_crash_after_provider_success_reconciles_without_reexecution(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
    effect: EffectRef,
    arguments: dict[str, object],
    expected_targets: tuple[str, ...],
) -> None:
    transport = ScriptedGitHub()
    operation_id = seq.next()
    if effect == EFFECT_CREATE_ISSUE_COMMENT:
        transport.enqueue(github_response(201, github_comment(operation_id)))
        transport.enqueue(github_response(200, [github_comment(operation_id)]))
    elif effect == EFFECT_ADD_LABEL:
        transport.enqueue(github_response(200, [{"name": "safe"}]))
        transport.enqueue(github_response(200, {"labels": [{"name": "safe"}]}))
    elif effect == EFFECT_CREATE_PULL_REQUEST:
        transport.enqueue(github_response(201, github_pull(operation_id)))
        transport.enqueue(github_response(200, [github_pull(operation_id)]))
    else:
        transport.enqueue(github_response(200, {"merged": True, "sha": "b" * 40}))
        transport.enqueue(github_response(200, github_pull(operation_id, merged=True)))

    crashing, _, recovery, _ = runtime_services(
        uow_factory,
        clock,
        transport,
        PolicyVerdict.ALLOW,
        crash_after=RuntimeCrashPoint.AFTER_EXECUTE_BEFORE_EVIDENCE,
    )
    submit = github_effect_submit(seq, operation_id, effect=effect, arguments=arguments)
    from stateback.runtime.commands import SubmitCommand

    assert isinstance(submit, SubmitCommand)
    with pytest.raises(SimulatedCrash):
        crashing.run(submit, execute_ids(seq))

    attempts = load_attempts(uow_factory, operation_id)
    assert len(attempts) == 1
    assert attempts[0].external_resource_ids == expected_targets

    for expected_state in (OperationState.UNKNOWN, OperationState.SUCCEEDED):
        current = load_operation(uow_factory, operation_id)
        result = recovery.recover(make_recovery(seq, operation_id, current.version))
        assert result.operation is not None
        assert result.operation.state is expected_state

    mutation_methods = [
        method for method, _, _ in transport.requests if method in {"POST", "PUT"}
    ]
    assert len(mutation_methods) == 1
    if effect == EFFECT_CREATE_PULL_REQUEST:
        assert transport.requests[-1][1] == (
            "/repos/acme/sandbox/pulls?"
            "state=all&head=acme%3Afeature&base=main&per_page=100"
        )
