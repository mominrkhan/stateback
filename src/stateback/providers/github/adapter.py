"""GitHub issue adapter preserving ambiguity and provider-specific limits."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from stateback.domain.capability import (
    CompensationEvidence,
    CompensationRequest,
    EffectDescriptor,
    ExecutionEvidence,
    ProviderExecutionContext,
    ProviderExecutionRequest,
    ValidationResult,
    VerificationEvidence,
)
from stateback.domain.enums import (
    CONTRACT_VERSION,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    VerificationTarget,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.jsonutil import JsonValue, json_from_plain
from stateback.domain.refs import EffectRef
from stateback.domain.verification import VerificationRequest
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.github.codec import (
    argument_map,
    create_payload,
    find_marked_issue,
    first_issue_resource,
    issue_identity,
    json_bytes,
    operation_marker,
    parse_object,
    required_str,
    resource_from_original_evidence,
    validate_arguments,
)
from stateback.providers.github.effects import (
    CREATE_ISSUE_DESCRIPTOR,
    EFFECT_CREATE_ISSUE,
    GITHUB_PROVIDER,
)
from stateback.providers.github.http import classify_http, retry_after
from stateback.providers.github.transport import (
    GitHubHttpResponse,
    GitHubTransport,
    UrllibGitHubTransport,
)
from stateback.runtime.clock import Clock

_EMPTY = json_from_plain({})
_DEFAULT_TIMEOUT_SECONDS = 15.0


class _MissingCredentialTransport:
    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
        timeout_seconds: float,
    ) -> GitHubHttpResponse:
        del method, path, body, timeout_seconds
        raise AssertionError("credential validation must prevent transport access")


class GitHubAdapter:
    def __init__(
        self,
        *,
        transport: GitHubTransport,
        clock: Clock,
        credential_configured: bool = True,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._credential_configured = credential_configured

    @classmethod
    def from_token(cls, *, token: str | None, clock: Clock) -> GitHubAdapter:
        if token is None or not token.strip():
            return cls(
                transport=_MissingCredentialTransport(),
                clock=clock,
                credential_configured=False,
            )
        return cls(transport=UrllibGitHubTransport(token=token), clock=clock)

    @classmethod
    def for_validation(
        cls, *, credential_configured: bool, clock: Clock
    ) -> GitHubAdapter:
        """Describe configured capability without giving this process a credential."""

        return cls(
            transport=_MissingCredentialTransport(),
            clock=clock,
            credential_configured=credential_configured,
        )

    def supported_effects(self) -> tuple[EffectRef, ...]:
        return (EFFECT_CREATE_ISSUE,)

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        if effect != EFFECT_CREATE_ISSUE:
            raise UnsupportedEffectError(effect)
        return CREATE_ISSUE_DESCRIPTOR

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        if request.effect != EFFECT_CREATE_ISSUE:
            return ValidationResult(
                accepted=False,
                error=self._error(
                    ErrorKind.UNSUPPORTED_CAPABILITY,
                    "github.validation.unknown_effect",
                ),
            )
        if not self._credential_configured:
            return ValidationResult(
                accepted=False,
                error=self._error(
                    ErrorKind.AUTHENTICATION,
                    "github.auth.missing_credential",
                ),
            )
        reason = validate_arguments(request.arguments)
        if reason is not None:
            return ValidationResult(
                accepted=False,
                error=self._error(ErrorKind.VALIDATION, reason),
            )
        return ValidationResult(accepted=True, error=None)

    def execute(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence:
        if request.effect != EFFECT_CREATE_ISSUE:
            raise UnsupportedEffectError(request.effect)
        validation = self.validate_execution(request)
        if not validation.accepted:
            return ExecutionEvidence(
                outcome=EffectOutcome.NOT_APPLIED,
                evidence=self._evidence(
                    source=EvidenceSource.EXECUTION_RESPONSE,
                    status="validation_rejected",
                    request_id=None,
                    external_operation_id=None,
                    external_resource_ids=(),
                    fields=_EMPTY,
                    raw_reference=None,
                ),
                error=validation.error,
                external_operation_id=None,
                external_resource_ids=(),
            )
        timeout = self._timeout(context)
        if timeout is None:
            return self._known_error(
                ErrorKind.TRANSIENT_TRANSPORT,
                "github.deadline.not_sent",
                status="deadline_expired",
                retryable=True,
            )
        args = argument_map(request.arguments)
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        payload = create_payload(args, operation_marker(context))
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues"
        try:
            response = self._transport.request(
                method="POST",
                path=path,
                body=json_bytes(payload),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            return self._unknown_transport(exc)
        if response.status != 201:
            return self._execution_http_error(response)
        parsed = parse_object(response.body)
        issue = issue_identity(parsed, owner=owner, repo=repo)
        if issue is None:
            return self._unknown_malformed(response)
        issue_id, resource_id, issue_number, html_url, state = issue
        evidence = self._evidence(
            source=EvidenceSource.EXECUTION_RESPONSE,
            status=state,
            request_id=response.header("x-github-request-id"),
            external_operation_id=issue_id,
            external_resource_ids=(resource_id,),
            fields=json_from_plain(
                {"issue_number": issue_number, "owner": owner, "repo": repo}
            ),
            raw_reference=html_url,
        )
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=evidence,
            error=None,
            external_operation_id=issue_id,
            external_resource_ids=(resource_id,),
        )

    def verify(
        self,
        context: ProviderExecutionContext,
        request: VerificationRequest,
    ) -> VerificationEvidence:
        if request.effect != EFFECT_CREATE_ISSUE:
            raise UnsupportedEffectError(request.effect)
        if not self._credential_configured:
            return self._verification_error(
                ErrorKind.AUTHENTICATION,
                "github.auth.missing_credential",
                status="authentication_failed",
            )
        resource = first_issue_resource(request.external_resource_ids)
        if resource is None:
            query = urlencode({"q": f'"{operation_marker(context)}" in:body is:issue'})
            path = f"/search/issues?{query}"
        else:
            owner, repo, number = resource
            path = (
                f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}"
            )
        try:
            response = self._transport.request(
                method="GET",
                path=path,
                body=None,
                timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return self._verification_transport(exc)
        if response.status != 200:
            return self._verification_http_error(response)
        if resource is not None:
            owner, repo, number = resource
            direct_identity = issue_identity(
                parse_object(response.body),
                owner=owner,
                repo=repo,
                expected_number=number,
            )
            if direct_identity is None:
                return self._verification_error(
                    ErrorKind.PROVIDER_INCONSISTENT,
                    "github.verify.identity_inconsistent",
                    status="identity_inconsistent",
                )
        found = find_marked_issue(
            response.body, marker=operation_marker(context), resource=resource
        )
        if found is None:
            return VerificationEvidence(
                outcome=EffectOutcome.UNKNOWN,
                evidence=self._evidence(
                    source=EvidenceSource.CUSTOM,
                    status="marker_not_observed",
                    request_id=response.header("x-github-request-id"),
                    external_operation_id=None,
                    external_resource_ids=(),
                    fields=json_from_plain(
                        {"absence_is_conclusive": False, "search_complete": False}
                    ),
                    raw_reference=None,
                ),
                error=self._error(
                    ErrorKind.TRANSIENT_TRANSPORT,
                    "github.verify.marker_not_observed",
                    retryable=True,
                ),
            )
        issue_id, resource_id, _, html_url, state = found
        if request.target is VerificationTarget.COMPENSATION and state != "closed":
            outcome = EffectOutcome.NOT_APPLIED
            status = "open"
        else:
            outcome = EffectOutcome.APPLIED
            status = state
        return VerificationEvidence(
            outcome=outcome,
            evidence=self._evidence(
                source=EvidenceSource.CUSTOM,
                status=status,
                request_id=response.header("x-github-request-id"),
                external_operation_id=issue_id,
                external_resource_ids=(resource_id,),
                fields=json_from_plain({"marker_matched": True}),
                raw_reference=html_url,
            ),
            error=None,
        )

    def compensate(
        self,
        context: ProviderExecutionContext,
        request: CompensationRequest,
    ) -> CompensationEvidence:
        del context
        if not self._credential_configured:
            return self._compensation_error(
                EffectOutcome.NOT_APPLIED,
                ErrorKind.AUTHENTICATION,
                "github.auth.missing_credential",
                status="authentication_failed",
            )
        resource = resource_from_original_evidence(request)
        if resource is None:
            return self._compensation_error(
                EffectOutcome.NOT_APPLIED,
                ErrorKind.VALIDATION,
                "github.compensation.issue_identity_missing",
                status="identity_missing",
            )
        owner, repo, number = resource
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}"
        try:
            response = self._transport.request(
                method="PATCH",
                path=path,
                body=json_bytes({"state": "closed"}),
                timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return self._compensation_transport(exc)
        if response.status != 200:
            return self._compensation_http_error(response)
        parsed = parse_object(response.body)
        issue = issue_identity(
            parsed,
            owner=owner,
            repo=repo,
            expected_number=number,
        )
        if issue is None or issue[4] != "closed":
            return self._compensation_error(
                EffectOutcome.UNKNOWN,
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.compensation.malformed_response",
                status="malformed",
                http=response.status,
            )
        issue_id, resource_id, _, html_url, state = issue
        return CompensationEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status=state,
                request_id=response.header("x-github-request-id"),
                external_operation_id=issue_id,
                external_resource_ids=(resource_id,),
                fields=json_from_plain(
                    {"mitigation": "closed_issue", "rollback": False}
                ),
                raw_reference=html_url,
            ),
            error=None,
            external_operation_id=issue_id,
        )

    def _timeout(self, context: ProviderExecutionContext) -> float | None:
        if context.deadline is None:
            return _DEFAULT_TIMEOUT_SECONDS
        remaining = (context.deadline.value - self._clock.now().value).total_seconds()
        return remaining if remaining > 0 else None

    def _execution_http_error(self, response: GitHubHttpResponse) -> ExecutionEvidence:
        kind, code, retryable, known = classify_http(response)
        outcome = EffectOutcome.NOT_APPLIED if known else EffectOutcome.UNKNOWN
        return ExecutionEvidence(
            outcome=outcome,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="rejected" if known else "ambiguous_http_failure",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
                raw_reference=None,
            ),
            error=self._error(
                kind,
                code,
                retryable=retryable,
                http=response.status,
                retry_after=retry_after(response),
            ),
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _verification_http_error(
        self, response: GitHubHttpResponse
    ) -> VerificationEvidence:
        kind, code, retryable, _ = classify_http(response)
        return self._verification_error(
            kind,
            code,
            status="verification_failed",
            retryable=retryable,
            http=response.status,
            retry_after=retry_after(response),
        )

    def _compensation_http_error(
        self, response: GitHubHttpResponse
    ) -> CompensationEvidence:
        kind, code, retryable, known = classify_http(response)
        return self._compensation_error(
            EffectOutcome.NOT_APPLIED if known else EffectOutcome.UNKNOWN,
            kind,
            code,
            status="rejected" if known else "ambiguous_http_failure",
            retryable=retryable,
            http=response.status,
            retry_after=retry_after(response),
        )

    def _known_error(
        self,
        kind: ErrorKind,
        code: str,
        *,
        status: str,
        retryable: bool,
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status=status,
                request_id=None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
                raw_reference=None,
            ),
            error=self._error(kind, code, retryable=retryable),
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _unknown_transport(self, exc: Exception) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="transport_ambiguous",
                request_id=None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=json_from_plain({"exception_type": type(exc).__name__}),
                raw_reference=None,
            ),
            error=self._error(
                ErrorKind.TRANSIENT_TRANSPORT,
                "github.transport.ambiguous",
                retryable=True,
            ),
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _unknown_malformed(self, response: GitHubHttpResponse) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="malformed",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=(),
                fields=_EMPTY,
                raw_reference=None,
            ),
            error=self._error(
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.execute.malformed_response",
                http=response.status,
            ),
            external_operation_id=None,
            external_resource_ids=(),
        )

    def _verification_transport(self, exc: Exception) -> VerificationEvidence:
        return self._verification_error(
            ErrorKind.TRANSIENT_TRANSPORT,
            "github.verify.transport",
            status="transport_failed",
            retryable=True,
            exception_type=type(exc).__name__,
        )

    def _compensation_transport(self, exc: Exception) -> CompensationEvidence:
        return self._compensation_error(
            EffectOutcome.UNKNOWN,
            ErrorKind.TRANSIENT_TRANSPORT,
            "github.compensation.transport_ambiguous",
            status="transport_ambiguous",
            retryable=True,
            exception_type=type(exc).__name__,
        )

    def _verification_error(
        self,
        kind: ErrorKind,
        code: str,
        *,
        status: str,
        retryable: bool = False,
        http: int | None = None,
        retry_after: int | None = None,
        exception_type: str | None = None,
    ) -> VerificationEvidence:
        fields = (
            _EMPTY
            if exception_type is None
            else json_from_plain({"exception_type": exception_type})
        )
        return VerificationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.CUSTOM,
                status=status,
                request_id=None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=fields,
                raw_reference=None,
            ),
            error=self._error(
                kind,
                code,
                retryable=retryable,
                http=http,
                retry_after=retry_after,
            ),
        )

    def _compensation_error(
        self,
        outcome: EffectOutcome,
        kind: ErrorKind,
        code: str,
        *,
        status: str,
        retryable: bool = False,
        http: int | None = None,
        retry_after: int | None = None,
        exception_type: str | None = None,
    ) -> CompensationEvidence:
        fields = (
            _EMPTY
            if exception_type is None
            else json_from_plain({"exception_type": exception_type})
        )
        return CompensationEvidence(
            outcome=outcome,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status=status,
                request_id=None,
                external_operation_id=None,
                external_resource_ids=(),
                fields=fields,
                raw_reference=None,
            ),
            error=self._error(
                kind,
                code,
                retryable=retryable,
                http=http,
                retry_after=retry_after,
            ),
            external_operation_id=None,
        )

    def _error(
        self,
        kind: ErrorKind,
        code: str,
        *,
        retryable: bool = False,
        http: int | None = None,
        retry_after: int | None = None,
    ) -> NormalizedError:
        return NormalizedError(
            contract_version=CONTRACT_VERSION,
            kind=kind,
            code=code,
            message=code,
            retryable_infrastructure=retryable,
            provider_http_status=http,
            provider_error_code=None,
            retry_after_seconds=retry_after,
            details=_EMPTY,
        )

    def _evidence(
        self,
        *,
        source: EvidenceSource,
        status: str,
        request_id: str | None,
        external_operation_id: str | None,
        external_resource_ids: tuple[str, ...],
        fields: JsonValue,
        raw_reference: str | None,
    ) -> ProviderEvidence:
        return ProviderEvidence(
            source=source,
            provider=GITHUB_PROVIDER,
            observed_at=self._clock.now(),
            provider_status=status,
            provider_request_id=request_id,
            external_operation_id=external_operation_id,
            external_resource_ids=external_resource_ids,
            evidence_fields=fields,
            raw_reference=raw_reference,
        )
