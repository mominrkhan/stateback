from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import replace
from http.client import HTTPMessage
from io import BytesIO

import pytest

from stateback.domain.capability import (
    CompensationEvidence,
    CompensationRequest,
    ExecutionEvidence,
    ProviderExecutionContext,
    ProviderExecutionRequest,
    VerificationEvidence,
)
from stateback.domain.enums import (
    CONTRACT_VERSION,
    CompensationKind,
    EffectOutcome,
    ErrorKind,
    IdempotencyMode,
    VerificationMode,
    VerificationTarget,
)
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest
from stateback.providers.github import (
    EFFECT_ADD_LABEL,
    EFFECT_CREATE_ISSUE,
    EFFECT_CREATE_ISSUE_COMMENT,
    EFFECT_CREATE_PULL_REQUEST,
    EFFECT_MERGE_PULL_REQUEST,
    GitHubAdapter,
    GitHubHttpResponse,
)
from stateback.providers.github.transport import (
    MAX_GITHUB_RESPONSE_BYTES,
    GitHubResponseTooLarge,
    UrllibGitHubTransport,
)
from stateback.providers.reference.clock import FixedClock
from tests.unit.domain.fixtures import TS

pytestmark = [pytest.mark.contract, pytest.mark.benchmark_correctness]

OPERATION_ID = OpaqueId(value="00000000-0000-4000-8000-00000000a001")
ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-00000000a002")
VERIFY_ID = OpaqueId(value="00000000-0000-4000-8000-00000000a003")
COMPENSATION_ID = OpaqueId(value="00000000-0000-4000-8000-00000000a004")
COMPENSATION_ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-00000000a005")
MARKER = f"<!-- stateback-operation:{OPERATION_ID.value} -->"


class ScriptedTransport:
    def __init__(self) -> None:
        self.responses: list[GitHubHttpResponse | Exception] = []
        self.requests: list[tuple[str, str, bytes | None, float]] = []

    def enqueue(self, response: GitHubHttpResponse | Exception) -> None:
        self.responses.append(response)

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
    ) -> GitHubHttpResponse:
        self.requests.append((method, path, body, timeout_seconds))
        scripted = self.responses.pop(0)
        if isinstance(scripted, Exception):
            raise scripted
        return scripted


def response(status: int, body: object, **headers: str) -> GitHubHttpResponse:
    return GitHubHttpResponse(
        status=status,
        headers=tuple(headers.items()),
        body=json.dumps(body).encode("utf-8"),
    )


def issue(
    *,
    state: str = "open",
    body: str = MARKER,
    number: int = 42,
    owner: str = "acme",
    repo: str = "sandbox",
) -> dict[str, object]:
    return {
        "id": 9001,
        "number": number,
        "html_url": f"https://github.com/{owner}/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{owner}/{repo}",
        "state": state,
        "body": body,
    }


def context() -> ProviderExecutionContext:
    return ProviderExecutionContext(
        operation_id=OPERATION_ID,
        attempt_id=ATTEMPT_ID,
        idempotency_identity=f"sb:v1:op:{OPERATION_ID.value}",
        provider_idempotency_key=None,
        correlation_id="corr-github",
        deadline=None,
    )


def execution_request() -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        effect=EFFECT_CREATE_ISSUE,
        arguments=json_from_plain(
            {
                "owner": "acme",
                "repo": "sandbox",
                "title": "Stateback sandbox issue",
                "body": "created by contract test",
                "labels": ["stateback"],
            }
        ),
    )


def adapter(transport: ScriptedTransport) -> GitHubAdapter:
    return GitHubAdapter(transport=transport, clock=FixedClock(TS))


def verification(
    *,
    target: VerificationTarget = VerificationTarget.ORIGINAL_EFFECT,
    resources: tuple[str, ...] = (),
) -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OPERATION_ID,
        operation_version=4,
        target=target,
        target_attempt_id=ATTEMPT_ID,
        effect=EFFECT_CREATE_ISSUE,
        external_operation_id=None,
        external_resource_ids=resources,
        idempotency_identity=f"sb:v1:op:{OPERATION_ID.value}",
        provider_evidence_refs=(),
        requested_at=TS,
    )


def original_evidence() -> ProviderEvidence:
    transport = ScriptedTransport()
    transport.enqueue(response(201, issue(), **{"x-github-request-id": "req-1"}))
    result = adapter(transport).execute(context(), execution_request())
    assert result.evidence is not None
    return result.evidence


def compensation_request() -> CompensationRequest:
    return CompensationRequest(
        original_operation_id=OPERATION_ID,
        compensation_id=COMPENSATION_ID,
        compensation_attempt_id=COMPENSATION_ATTEMPT_ID,
        original_evidence=(original_evidence(),),
        compensation_arguments=execution_request().arguments,
        idempotency_identity=f"sb:v1:comp:{COMPENSATION_ID.value}",
        provider_idempotency_key=None,
    )


def test_capabilities_are_honest_about_no_idempotency_and_mitigation() -> None:
    transport = ScriptedTransport()
    descriptor = adapter(transport).descriptor(EFFECT_CREATE_ISSUE)
    assert descriptor.idempotency_mode is IdempotencyMode.NONE
    assert descriptor.provider_key_semantics is None
    assert descriptor.verification_mode is VerificationMode.CUSTOM
    assert descriptor.compensation_kind is CompensationKind.MITIGATING


def test_missing_credential_and_invalid_arguments_fail_before_network() -> None:
    missing = GitHubAdapter.from_token(token=None, clock=FixedClock(TS))
    result = missing.validate_execution(execution_request())
    assert result.accepted is False
    assert result.error is not None
    assert result.error.kind is ErrorKind.AUTHENTICATION

    transport = ScriptedTransport()
    invalid = ProviderExecutionRequest(
        effect=EFFECT_CREATE_ISSUE,
        arguments=json_from_plain({"owner": "acme", "repo": "sandbox"}),
    )
    rejected = adapter(transport).execute(context(), invalid)
    assert rejected.outcome is EffectOutcome.NOT_APPLIED
    assert transport.requests == []


def test_non_secret_capability_signal_validates_without_provider_authority() -> None:
    configured = GitHubAdapter.for_validation(
        credential_configured=True, clock=FixedClock(TS)
    )
    assert configured.validate_execution(execution_request()).accepted is True
    execution = configured.execute(context(), execution_request())
    assert execution.outcome is EffectOutcome.UNKNOWN
    assert execution.error is not None
    assert execution.error.kind is ErrorKind.TRANSIENT_TRANSPORT


def test_execute_appends_marker_and_returns_external_identity() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(201, issue(), **{"x-github-request-id": "req-2"}))
    result = adapter(transport).execute(context(), execution_request())
    assert result.outcome is EffectOutcome.APPLIED
    assert result.external_operation_id == "github:issue:9001"
    assert result.external_resource_ids == ("acme/sandbox#42",)
    method, path, body, _ = transport.requests[0]
    assert method == "POST"
    assert path == "/repos/acme/sandbox/issues"
    assert body is not None
    assert MARKER in json.loads(body)["body"]


@pytest.mark.parametrize(
    ("status", "headers", "outcome", "kind"),
    [
        (422, {}, EffectOutcome.NOT_APPLIED, ErrorKind.PROVIDER_REJECTED),
        (401, {}, EffectOutcome.NOT_APPLIED, ErrorKind.AUTHENTICATION),
        (
            429,
            {"retry-after": "30"},
            EffectOutcome.NOT_APPLIED,
            ErrorKind.RATE_LIMITED,
        ),
        (503, {}, EffectOutcome.UNKNOWN, ErrorKind.PROVIDER_UNAVAILABLE),
        (302, {}, EffectOutcome.UNKNOWN, ErrorKind.PROVIDER_REJECTED),
        (418, {}, EffectOutcome.UNKNOWN, ErrorKind.PROVIDER_REJECTED),
    ],
)
def test_execute_normalizes_http_failure_without_erasing_ambiguity(
    status: int,
    headers: dict[str, str],
    outcome: EffectOutcome,
    kind: ErrorKind,
) -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(status, {"message": "redacted"}, **headers))
    result = adapter(transport).execute(context(), execution_request())
    assert result.outcome is outcome
    assert result.error is not None
    assert result.error.kind is kind
    if status == 429:
        assert result.error.retry_after_seconds == 30


def test_transport_and_malformed_success_are_unknown() -> None:
    transport = ScriptedTransport()
    transport.enqueue(TimeoutError("token=must-not-leak"))
    timed_out = adapter(transport).execute(context(), execution_request())
    assert timed_out.outcome is EffectOutcome.UNKNOWN
    assert timed_out.error is not None
    assert "must-not-leak" not in str(timed_out.to_wire())

    transport.enqueue(response(201, {"number": 42}))
    malformed = adapter(transport).execute(context(), execution_request())
    assert malformed.outcome is EffectOutcome.UNKNOWN
    assert malformed.error is not None
    assert malformed.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE

    transport.enqueue(
        response(201, issue(number=43) | {"html_url": issue()["html_url"]})
    )
    inconsistent = adapter(transport).execute(context(), execution_request())
    assert inconsistent.outcome is EffectOutcome.UNKNOWN
    assert inconsistent.error is not None
    assert inconsistent.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE


def test_search_verification_proves_presence_but_not_absence() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, {"items": [issue()]}))
    found = adapter(transport).verify(context(), verification())
    assert found.outcome is EffectOutcome.APPLIED
    assert transport.requests[0][0] == "GET"
    assert transport.requests[0][1].startswith("/search/issues?")

    transport.enqueue(response(200, {"items": []}))
    absent = adapter(transport).verify(context(), verification())
    assert absent.outcome is EffectOutcome.UNKNOWN
    assert absent.error is not None
    assert absent.error.code == "github.verify.marker_not_observed"


def test_direct_verification_rejects_contradictory_issue_identity() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, issue(number=43)))
    result = adapter(transport).verify(
        context(), verification(resources=("acme/sandbox#42",))
    )
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.PROVIDER_INCONSISTENT
    assert result.error.code == "github.verify.identity_inconsistent"


def test_compensation_closes_issue_and_verification_reads_state() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, issue(state="closed")))
    compensated = adapter(transport).compensate(context(), compensation_request())
    assert compensated.outcome is EffectOutcome.APPLIED
    assert compensated.evidence is not None
    assert compensated.evidence.evidence_fields == json_from_plain(
        {"mitigation": "closed_issue", "rollback": False}
    )
    assert transport.requests[0][0] == "PATCH"

    transport.enqueue(response(200, issue(state="open")))
    not_closed = adapter(transport).verify(
        context(),
        verification(
            target=VerificationTarget.COMPENSATION,
            resources=("acme/sandbox#42",),
        ),
    )
    assert not_closed.outcome is EffectOutcome.NOT_APPLIED

    transport.enqueue(response(200, issue(state="closed")))
    closed = adapter(transport).verify(
        context(),
        verification(
            target=VerificationTarget.COMPENSATION,
            resources=("acme/sandbox#42",),
        ),
    )
    assert closed.outcome is EffectOutcome.APPLIED


def test_compensation_rejects_contradictory_issue_identity() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, issue(state="closed", number=43)))
    result = adapter(transport).compensate(context(), compensation_request())
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE


def test_urllib_transport_rejects_redirect_without_forwarding_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectingOpener:
        def __init__(self, handler: urllib.request.HTTPRedirectHandler) -> None:
            self.handler = handler
            self.requests: list[urllib.request.Request] = []

        def open(self, request: urllib.request.Request, *, timeout: float) -> object:
            del timeout
            self.requests.append(request)
            redirected = self.handler.redirect_request(
                request,
                BytesIO(),
                302,
                "Found",
                HTTPMessage(),
                "https://attacker.invalid/collect",
            )
            assert redirected is None
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                HTTPMessage(),
                BytesIO(b""),
            )

    openers: list[RedirectingOpener] = []

    def build_opener(
        handler: urllib.request.HTTPRedirectHandler,
    ) -> RedirectingOpener:
        opener = RedirectingOpener(handler)
        openers.append(opener)
        return opener

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    transport = UrllibGitHubTransport(token="github_pat_test_only")
    result = GitHubAdapter(transport=transport, clock=FixedClock(TS)).execute(
        context(), execution_request()
    )
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.code == "github.http.ambiguous"
    assert len(openers[0].requests) == 1
    assert openers[0].requests[0].full_url.startswith("https://api.github.com/")
    assert openers[0].requests[0].get_header("User-agent") == "stateback/0.1.0"


@pytest.mark.parametrize(
    "api_url",
    [
        "http://api.github.com",
        "https://token@api.github.com",
        "https://api.github.com?destination=attacker.invalid",
        "https://api.github.com#attacker",
        "https://attacker.invalid",
        "https://api.github.com:444",
        "https://api.github.com/evil",
        "https://api.github.com/",
        "https://api.github.com\n",
    ],
)
def test_urllib_transport_rejects_unsafe_api_origins(api_url: str) -> None:
    with pytest.raises(ValueError, match="credential-free HTTPS origin"):
        UrllibGitHubTransport(token="github_pat_test_only", api_url=api_url)


class _OversizedResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.headers = HTTPMessage()

    def __enter__(self) -> _OversizedResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self, amount: int) -> bytes:
        assert amount == MAX_GITHUB_RESPONSE_BYTES + 1
        return b"x" * amount


class _OversizedOpener:
    def __init__(self, status: int) -> None:
        self.status = status

    def open(self, request: urllib.request.Request, *, timeout: float) -> object:
        del request, timeout
        return _OversizedResponse(self.status)


@pytest.mark.parametrize("operation", ["execute", "verify", "compensate"])
def test_oversized_success_response_remains_unknown_without_retaining_body(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *handlers: _OversizedOpener(201 if operation == "execute" else 200),
    )
    github = GitHubAdapter(
        transport=UrllibGitHubTransport(token="github_pat_test_only"),
        clock=FixedClock(TS),
    )
    result: ExecutionEvidence | VerificationEvidence | CompensationEvidence
    if operation == "execute":
        result = github.execute(context(), execution_request())
    elif operation == "verify":
        result = github.verify(context(), verification(resources=("acme/sandbox#42",)))
    else:
        result = github.compensate(context(), compensation_request())
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert "xxxxxxxx" not in str(result.to_wire())


def test_oversized_http_error_response_raises_bounded_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ErrorOpener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> object:
            del timeout
            raise urllib.error.HTTPError(
                request.full_url,
                422,
                "Unprocessable Entity",
                HTTPMessage(),
                BytesIO(b"x" * (MAX_GITHUB_RESPONSE_BYTES + 1)),
            )

    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda *handlers: ErrorOpener(),
    )
    transport = UrllibGitHubTransport(token="github_pat_test_only")
    with pytest.raises(GitHubResponseTooLarge, match="supported size"):
        transport.request(
            method="POST",
            path="/repos/acme/sandbox/issues",
            body=b"{}",
            timeout_seconds=1,
        )


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("html_url", "https://attacker.invalid/acme/sandbox/issues/42"),
        ("repository_url", "https://attacker.invalid/repos/acme/sandbox"),
        ("html_url", "https://github.com@attacker.invalid/acme/sandbox/issues/42"),
        ("html_url", "https://github.com/evil/acme/sandbox/issues/42"),
        (
            "repository_url",
            "https://api.github.com/evil/repos/acme/sandbox",
        ),
    ],
)
def test_provider_identity_rejects_forged_github_urls(field: str, url: str) -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(201, issue() | {field: url}))
    result = adapter(transport).execute(context(), execution_request())
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("html_url", "https://github.com:abc/acme/sandbox/issues/42"),
        ("repository_url", "https://[invalid/repos/acme/sandbox"),
    ],
)
@pytest.mark.parametrize("operation", ["execute", "verify", "compensate"])
def test_malformed_provider_url_syntax_remains_canonical_unknown(
    field: str,
    url: str,
    operation: str,
) -> None:
    transport = ScriptedTransport()
    payload = issue(state="closed" if operation == "compensate" else "open") | {
        field: url
    }
    transport.enqueue(response(201 if operation == "execute" else 200, payload))
    github = adapter(transport)
    result: ExecutionEvidence | VerificationEvidence | CompensationEvidence
    if operation == "execute":
        result = github.execute(context(), execution_request())
    elif operation == "verify":
        result = github.verify(context(), verification(resources=("acme/sandbox#42",)))
    else:
        result = github.compensate(context(), compensation_request())
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind in {
        ErrorKind.MALFORMED_PROVIDER_RESPONSE,
        ErrorKind.PROVIDER_INCONSISTENT,
    }


def workflow_request(
    effect: EffectRef, arguments: dict[str, object]
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(effect=effect, arguments=json_from_plain(arguments))


def workflow_verification(
    effect: EffectRef, resources: tuple[str, ...]
) -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OPERATION_ID,
        operation_version=4,
        target=VerificationTarget.ORIGINAL_EFFECT,
        target_attempt_id=ATTEMPT_ID,
        effect=effect,
        external_operation_id=None,
        external_resource_ids=resources,
        idempotency_identity=f"sb:v1:op:{OPERATION_ID.value}",
        provider_evidence_refs=(),
        requested_at=TS,
    )


def pull(
    *,
    merged: bool = False,
    head_sha: str = "a" * 40,
    head_ref: str = "feature",
    head_label: str = "acme:feature",
    base_ref: str = "main",
) -> dict[str, object]:
    return {
        "id": 7001,
        "number": 17,
        "html_url": "https://github.com/acme/sandbox/pull/17",
        "state": "closed" if merged else "open",
        "body": MARKER,
        "head": {
            "sha": head_sha,
            "ref": head_ref,
            "label": head_label,
            "repo": {"full_name": "acme/sandbox"},
        },
        "base": {"ref": base_ref, "repo": {"full_name": "acme/sandbox"}},
        "merged": merged,
    }


WORKFLOW_CASES: tuple[tuple[EffectRef, dict[str, object]], ...] = (
    (
        EFFECT_CREATE_ISSUE_COMMENT,
        {"owner": "acme", "repo": "sandbox", "issue_number": 42, "body": "note"},
    ),
    (
        EFFECT_ADD_LABEL,
        {"owner": "acme", "repo": "sandbox", "issue_number": 42, "label": "safe"},
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
    ),
    (
        EFFECT_MERGE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
        },
    ),
)


def test_v01_workflow_descriptors_are_conservative() -> None:
    github = adapter(ScriptedTransport())
    expected = {
        EFFECT_CREATE_ISSUE: (IdempotencyMode.NONE, CompensationKind.MITIGATING),
        EFFECT_CREATE_ISSUE_COMMENT: (IdempotencyMode.NONE, CompensationKind.NONE),
        EFFECT_ADD_LABEL: (IdempotencyMode.NATURAL, CompensationKind.NONE),
        EFFECT_CREATE_PULL_REQUEST: (IdempotencyMode.NONE, CompensationKind.MITIGATING),
        EFFECT_MERGE_PULL_REQUEST: (IdempotencyMode.NONE, CompensationKind.NONE),
    }
    assert set(github.supported_effects()) == set(expected)
    for effect, (idempotency, compensation) in expected.items():
        descriptor = github.descriptor(effect)
        assert descriptor.idempotency_mode is idempotency
        assert descriptor.compensation_kind is compensation


@pytest.mark.parametrize(("effect", "arguments"), WORKFLOW_CASES)
def test_workflow_known_rejection_retains_verification_targets(
    effect: EffectRef, arguments: dict[str, object]
) -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(422, {"message": "rejected"}))
    github = adapter(transport)
    request = workflow_request(effect, arguments)
    result = github.execute(context(), request)
    assert result.outcome is EffectOutcome.NOT_APPLIED
    assert result.external_resource_ids == github.verification_resource_ids(request)


@pytest.mark.parametrize(("effect", "arguments"), WORKFLOW_CASES)
def test_workflow_transport_ambiguity_retains_verification_targets(
    effect: EffectRef, arguments: dict[str, object]
) -> None:
    transport = ScriptedTransport()
    transport.enqueue(TimeoutError("response lost"))
    github = adapter(transport)
    request = workflow_request(effect, arguments)
    result = github.execute(context(), request)
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.external_resource_ids == github.verification_resource_ids(request)


@pytest.mark.parametrize(("effect", "arguments"), WORKFLOW_CASES)
def test_workflow_malformed_success_retains_verification_targets(
    effect: EffectRef, arguments: dict[str, object]
) -> None:
    transport = ScriptedTransport()
    success_status = (
        200 if effect in {EFFECT_ADD_LABEL, EFFECT_MERGE_PULL_REQUEST} else 201
    )
    transport.enqueue(response(success_status, {}))
    github = adapter(transport)
    request = workflow_request(effect, arguments)
    result = github.execute(context(), request)
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE
    assert result.external_resource_ids == github.verification_resource_ids(request)


@pytest.mark.parametrize(("effect", "arguments"), WORKFLOW_CASES)
def test_workflow_missing_credential_and_expired_deadline_never_send(
    effect: EffectRef, arguments: dict[str, object]
) -> None:
    request = workflow_request(effect, arguments)
    missing_transport = ScriptedTransport()
    missing = GitHubAdapter(
        transport=missing_transport,
        clock=FixedClock(TS),
        credential_configured=False,
    ).execute(context(), request)
    assert missing.outcome is EffectOutcome.NOT_APPLIED
    assert missing.error is not None
    assert missing.error.kind is ErrorKind.AUTHENTICATION
    assert missing_transport.requests == []

    expired_transport = ScriptedTransport()
    expired = adapter(expired_transport).execute(
        replace(context(), deadline=TS), request
    )
    assert expired.outcome is EffectOutcome.NOT_APPLIED
    assert expired.error is not None
    assert expired.error.code == "github.deadline.not_sent"
    assert expired_transport.requests == []


def test_create_comment_marks_body_and_verifies_positive_presence() -> None:
    request = workflow_request(
        EFFECT_CREATE_ISSUE_COMMENT,
        {"owner": "acme", "repo": "sandbox", "issue_number": 42, "body": "note"},
    )
    comment = {
        "id": 81,
        "html_url": "https://github.com/acme/sandbox/issues/42#issuecomment-81",
        "issue_url": "https://api.github.com/repos/acme/sandbox/issues/42",
        "body": f"note\n\n{MARKER}",
    }
    transport = ScriptedTransport()
    transport.enqueue(response(201, comment))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.APPLIED
    assert MARKER in json.loads(transport.requests[0][2] or b"{}")["body"]
    transport.enqueue(response(200, comment))
    verified = adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_CREATE_ISSUE_COMMENT, result.external_resource_ids
        ),
    )
    assert verified.outcome is EffectOutcome.APPLIED


def test_comment_transport_ambiguity_keeps_target_and_absence_is_unknown() -> None:
    request = workflow_request(
        EFFECT_CREATE_ISSUE_COMMENT,
        {"owner": "acme", "repo": "sandbox", "issue_number": 42, "body": "note"},
    )
    transport = ScriptedTransport()
    transport.enqueue(TimeoutError("lost response"))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.external_resource_ids == ("github:issue-target:acme/sandbox#42",)
    transport.enqueue(response(200, []))
    verified = adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_CREATE_ISSUE_COMMENT, result.external_resource_ids
        ),
    )
    assert verified.outcome is EffectOutcome.UNKNOWN


def test_add_label_is_natural_and_read_back_can_prove_absence() -> None:
    request = workflow_request(
        EFFECT_ADD_LABEL,
        {"owner": "acme", "repo": "sandbox", "issue_number": 42, "label": "safe"},
    )
    transport = ScriptedTransport()
    transport.enqueue(response(200, [{"name": "safe"}]))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.APPLIED
    assert json.loads(transport.requests[0][2] or b"{}") == {"labels": ["safe"]}
    transport.enqueue(response(200, issue() | {"labels": []}))
    verified = adapter(transport).verify(
        context(), workflow_verification(EFFECT_ADD_LABEL, result.external_resource_ids)
    )
    assert verified.outcome is EffectOutcome.NOT_APPLIED


def test_create_pull_request_marks_body_and_absence_stays_unknown() -> None:
    request = workflow_request(
        EFFECT_CREATE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "head": "feature",
            "base": "main",
            "title": "Safe change",
            "body": "details",
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(201, pull()))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.APPLIED
    assert MARKER in json.loads(transport.requests[0][2] or b"{}")["body"]
    transport.enqueue(response(200, []))
    unknown = adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_CREATE_PULL_REQUEST,
            (
                "github:repository:acme/sandbox",
                "github:head-ref:feature",
                "github:base-ref:main",
            ),
        ),
    )
    assert unknown.outcome is EffectOutcome.UNKNOWN
    assert transport.requests[-1][1] == (
        "/repos/acme/sandbox/pulls?state=all&head=acme%3Afeature&base=main&per_page=100"
    )


def test_create_pull_verification_preserves_qualified_fork_head_filter() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, []))
    adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_CREATE_PULL_REQUEST,
            (
                "github:repository:acme/sandbox",
                "github:head-ref:contributor:feature",
                "github:base-ref:main",
            ),
        ),
    )
    assert transport.requests[-1][1] == (
        "/repos/acme/sandbox/pulls?"
        "state=all&head=contributor%3Afeature&base=main&per_page=100"
    )


@pytest.mark.parametrize(
    "provider_pull",
    [pull(head_ref="other"), pull(base_ref="release")],
)
def test_create_pull_request_never_accepts_intent_inconsistent_response(
    provider_pull: dict[str, object],
) -> None:
    request = workflow_request(
        EFFECT_CREATE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "head": "feature",
            "base": "main",
            "title": "Safe change",
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(201, provider_pull))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.PROVIDER_INCONSISTENT


def test_create_pull_verification_rejects_intent_inconsistent_direct_read() -> None:
    transport = ScriptedTransport()
    transport.enqueue(response(200, pull(head_ref="other")))
    result = adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_CREATE_PULL_REQUEST,
            (
                "github:pull:acme/sandbox#17",
                "github:head-ref:feature",
                "github:base-ref:main",
            ),
        ),
    )
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.PROVIDER_INCONSISTENT


def test_create_pull_compensation_closes_only_the_known_pull() -> None:
    request = workflow_request(
        EFFECT_CREATE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "head": "feature",
            "base": "main",
            "title": "Safe change",
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(201, pull()))
    github = adapter(transport)
    executed = github.execute(context(), request)
    assert executed.evidence is not None
    transport.enqueue(response(200, pull() | {"state": "closed"}))
    compensated = github.compensate(
        context(),
        CompensationRequest(
            original_operation_id=OPERATION_ID,
            compensation_id=COMPENSATION_ID,
            compensation_attempt_id=COMPENSATION_ATTEMPT_ID,
            original_evidence=(executed.evidence,),
            compensation_arguments=request.arguments,
            idempotency_identity=f"sb:v1:comp:{COMPENSATION_ID.value}",
            provider_idempotency_key=None,
        ),
    )
    assert compensated.outcome is EffectOutcome.APPLIED
    assert transport.requests[-1][0:2] == (
        "PATCH",
        "/repos/acme/sandbox/pulls/17",
    )


def test_merge_binds_expected_head_and_verification_rejects_changed_head() -> None:
    request = workflow_request(
        EFFECT_MERGE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
            "merge_method": "squash",
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(200, {"merged": True, "sha": "b" * 40}))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.APPLIED
    assert json.loads(transport.requests[0][2] or b"{}") == {
        "merge_method": "squash",
        "sha": "a" * 40,
    }
    transport.enqueue(response(200, pull(merged=True, head_sha="c" * 40)))
    verified = adapter(transport).verify(
        context(),
        workflow_verification(EFFECT_MERGE_PULL_REQUEST, result.external_resource_ids),
    )
    assert verified.outcome is EffectOutcome.UNKNOWN
    assert verified.error is not None
    assert verified.error.code == "github.verify.merge_head_changed"


@pytest.mark.parametrize("merged", [None, "true", 1])
def test_merge_verification_requires_explicit_boolean_merged(
    merged: object,
) -> None:
    provider_pull = pull()
    if merged is None:
        provider_pull.pop("merged")
    else:
        provider_pull["merged"] = merged
    transport = ScriptedTransport()
    transport.enqueue(response(200, provider_pull))
    verified = adapter(transport).verify(
        context(),
        workflow_verification(
            EFFECT_MERGE_PULL_REQUEST,
            ("github:pull:acme/sandbox#17", f"github:head-sha:{'a' * 40}"),
        ),
    )
    assert verified.outcome is EffectOutcome.UNKNOWN
    assert verified.error is not None
    assert verified.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE


@pytest.mark.parametrize("merge_sha", ["", "abc", "z" * 40, 123])
def test_merge_success_requires_well_formed_merge_sha(merge_sha: object) -> None:
    request = workflow_request(
        EFFECT_MERGE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(200, {"merged": True, "sha": merge_sha}))
    result = adapter(transport).execute(context(), request)
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.error is not None
    assert result.error.kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE


def test_merge_conclusive_not_merged_response_is_not_unknown() -> None:
    request = workflow_request(
        EFFECT_MERGE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(200, {"merged": False, "message": "Head was modified"}))

    result = adapter(transport).execute(context(), request)

    assert result.outcome is EffectOutcome.NOT_APPLIED
    assert result.error is not None
    assert result.error.code == "github.merge.not_applied"
    assert result.external_resource_ids == (
        "github:pull:acme/sandbox#17",
        f"github:head-sha:{'a' * 40}",
    )


@pytest.mark.parametrize("status", [405, 409])
def test_merge_documented_rejections_prove_not_applied(status: int) -> None:
    request = workflow_request(
        EFFECT_MERGE_PULL_REQUEST,
        {
            "owner": "acme",
            "repo": "sandbox",
            "pull_number": 17,
            "head_sha": "a" * 40,
        },
    )
    transport = ScriptedTransport()
    transport.enqueue(response(status, {"message": "Merge cannot be performed"}))

    result = adapter(transport).execute(context(), request)

    assert result.outcome is EffectOutcome.NOT_APPLIED
    assert result.error is not None
    assert result.error.code == "github.merge.rejected"


@pytest.mark.parametrize(
    ("effect", "arguments"),
    [
        (
            EFFECT_CREATE_ISSUE_COMMENT,
            {"owner": "acme", "repo": "sandbox", "issue_number": 0, "body": "x"},
        ),
        (
            EFFECT_ADD_LABEL,
            {"owner": "acme", "repo": "sandbox", "issue_number": 1, "label": ""},
        ),
        (
            EFFECT_CREATE_PULL_REQUEST,
            {"owner": "acme", "repo": "sandbox", "head": "h", "base": "b"},
        ),
        (
            EFFECT_MERGE_PULL_REQUEST,
            {"owner": "acme", "repo": "sandbox", "pull_number": 1, "head_sha": "wrong"},
        ),
    ],
)
def test_workflow_validation_rejects_before_network(
    effect: EffectRef, arguments: dict[str, object]
) -> None:
    transport = ScriptedTransport()
    result = adapter(transport).execute(context(), workflow_request(effect, arguments))
    assert result.outcome is EffectOutcome.NOT_APPLIED
    assert transport.requests == []
