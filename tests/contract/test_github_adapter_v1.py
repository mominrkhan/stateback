from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.client import HTTPMessage
from io import BytesIO

import pytest

from stateback.domain.capability import (
    CompensationRequest,
    ProviderExecutionContext,
    ProviderExecutionRequest,
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
from stateback.domain.verification import VerificationRequest
from stateback.providers.github import (
    EFFECT_CREATE_ISSUE,
    GitHubAdapter,
    GitHubHttpResponse,
)
from stateback.providers.github.transport import UrllibGitHubTransport
from stateback.providers.reference.clock import FixedClock
from tests.unit.domain.fixtures import TS

pytestmark = pytest.mark.contract

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
