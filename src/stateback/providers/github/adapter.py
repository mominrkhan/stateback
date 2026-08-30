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
    comment_identity,
    create_payload,
    find_marked_issue,
    first_issue_resource,
    issue_identity,
    issue_target,
    json_bytes,
    marked_body,
    operation_marker,
    parse_array,
    parse_object,
    parse_prefixed_resource,
    parse_target_resource,
    pull_identity,
    pull_matches_intent,
    pull_payload,
    pull_target,
    required_int,
    required_str,
    resource_from_original_evidence,
    valid_git_sha,
    validate_arguments,
)
from stateback.providers.github.effects import (
    EFFECT_ADD_LABEL,
    EFFECT_CREATE_ISSUE,
    EFFECT_CREATE_ISSUE_COMMENT,
    EFFECT_CREATE_PULL_REQUEST,
    GITHUB_DESCRIPTORS,
    GITHUB_EFFECTS,
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
        return GITHUB_EFFECTS

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        descriptor = GITHUB_DESCRIPTORS.get(effect)
        if descriptor is None:
            raise UnsupportedEffectError(effect)
        return descriptor

    def validate_execution(self, request: ProviderExecutionRequest) -> ValidationResult:
        if request.effect not in GITHUB_DESCRIPTORS:
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
        reason = validate_arguments(request.effect, request.arguments)
        if reason is not None:
            return ValidationResult(
                accepted=False,
                error=self._error(ErrorKind.VALIDATION, reason),
            )
        return ValidationResult(accepted=True, error=None)

    def verification_resource_ids(
        self, request: ProviderExecutionRequest
    ) -> tuple[str, ...]:
        if request.effect not in GITHUB_DESCRIPTORS:
            raise UnsupportedEffectError(request.effect)
        args = argument_map(request.arguments)
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        if request.effect == EFFECT_CREATE_ISSUE:
            return ()
        if request.effect == EFFECT_CREATE_ISSUE_COMMENT:
            return (issue_target(owner, repo, required_int(args, "issue_number")),)
        if request.effect == EFFECT_ADD_LABEL:
            return (
                issue_target(owner, repo, required_int(args, "issue_number")),
                f"github:label:{required_str(args, 'label')}",
            )
        if request.effect == EFFECT_CREATE_PULL_REQUEST:
            return (
                f"github:repository:{owner}/{repo}",
                f"github:head-ref:{required_str(args, 'head')}",
                f"github:base-ref:{required_str(args, 'base')}",
            )
        return (
            pull_target(owner, repo, required_int(args, "pull_number")),
            f"github:head-sha:{required_str(args, 'head_sha').lower()}",
        )

    def execute(
        self,
        context: ProviderExecutionContext,
        request: ProviderExecutionRequest,
    ) -> ExecutionEvidence:
        if request.effect == EFFECT_CREATE_ISSUE:
            return self._execute_create_issue(context, request)
        if request.effect not in GITHUB_DESCRIPTORS:
            raise UnsupportedEffectError(request.effect)
        validation = self.validate_execution(request)
        if not validation.accepted:
            return self._validation_rejected(validation)
        timeout = self._timeout(context)
        if timeout is None:
            return self._known_error(
                ErrorKind.TRANSIENT_TRANSPORT,
                "github.deadline.not_sent",
                status="deadline_expired",
                retryable=True,
            )
        args = argument_map(request.arguments)
        if request.effect == EFFECT_CREATE_ISSUE_COMMENT:
            return self._execute_comment(context, args, timeout)
        if request.effect == EFFECT_ADD_LABEL:
            return self._execute_add_label(args, timeout)
        if request.effect == EFFECT_CREATE_PULL_REQUEST:
            return self._execute_create_pull(context, args, timeout)
        return self._execute_merge(args, timeout)

    def _execute_create_issue(
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
        targets = self.verification_resource_ids(request)
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
            return self._unknown_transport(exc, external_resource_ids=targets)
        if response.status != 201:
            return self._execution_http_error(response, external_resource_ids=targets)
        parsed = parse_object(response.body)
        issue = issue_identity(parsed, owner=owner, repo=repo)
        if issue is None:
            return self._unknown_malformed(response, external_resource_ids=targets)
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
        if request.effect == EFFECT_CREATE_ISSUE:
            return self._verify_create_issue(context, request)
        if request.effect not in GITHUB_DESCRIPTORS:
            raise UnsupportedEffectError(request.effect)
        if not self._credential_configured:
            return self._verification_error(
                ErrorKind.AUTHENTICATION,
                "github.auth.missing_credential",
                status="authentication_failed",
            )
        if request.effect == EFFECT_CREATE_ISSUE_COMMENT:
            return self._verify_comment(context, request)
        if request.effect == EFFECT_ADD_LABEL:
            return self._verify_label(request)
        if request.effect == EFFECT_CREATE_PULL_REQUEST:
            return self._verify_pull(context, request)
        return self._verify_merge(request)

    def _verify_create_issue(
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

    def _validation_rejected(self, validation: ValidationResult) -> ExecutionEvidence:
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

    def _execute_comment(
        self,
        context: ProviderExecutionContext,
        args: dict[str, JsonValue],
        timeout: float,
    ) -> ExecutionEvidence:
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        number = required_int(args, "issue_number")
        target = issue_target(owner, repo, number)
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}/comments"
        try:
            response = self._transport.request(
                method="POST",
                path=path,
                body=json_bytes({"body": marked_body(args, operation_marker(context))}),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            return self._unknown_transport(exc, external_resource_ids=(target,))
        if response.status != 201:
            return self._execution_http_error(response, external_resource_ids=(target,))
        comment = comment_identity(
            parse_object(response.body), owner=owner, repo=repo, issue_number=number
        )
        if comment is None:
            return self._unknown_malformed(response, external_resource_ids=(target,))
        operation_id, resource_id, _, comment_id, html_url = comment
        resources = (target, resource_id)
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="created",
                request_id=response.header("x-github-request-id"),
                external_operation_id=operation_id,
                external_resource_ids=resources,
                fields=json_from_plain(
                    {
                        "owner": owner,
                        "repo": repo,
                        "issue_number": number,
                        "comment_id": comment_id,
                    }
                ),
                raw_reference=html_url,
            ),
            error=None,
            external_operation_id=operation_id,
            external_resource_ids=resources,
        )

    def _execute_add_label(
        self, args: dict[str, JsonValue], timeout: float
    ) -> ExecutionEvidence:
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        number = required_int(args, "issue_number")
        label = required_str(args, "label")
        resources = (issue_target(owner, repo, number), f"github:label:{label}")
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}/labels"
        try:
            response = self._transport.request(
                method="POST",
                path=path,
                body=json_bytes({"labels": [label]}),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            return self._unknown_transport(exc, external_resource_ids=resources)
        if response.status != 200:
            return self._execution_http_error(response, external_resource_ids=resources)
        labels = parse_array(response.body)
        if labels is None or not any(item.get("name") == label for item in labels):
            return self._unknown_malformed(response, external_resource_ids=resources)
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="present",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=resources,
                fields=json_from_plain(
                    {
                        "owner": owner,
                        "repo": repo,
                        "issue_number": number,
                        "label": label,
                    }
                ),
                raw_reference=f"https://github.com/{owner}/{repo}/issues/{number}",
            ),
            error=None,
            external_operation_id=None,
            external_resource_ids=resources,
        )

    def _execute_create_pull(
        self,
        context: ProviderExecutionContext,
        args: dict[str, JsonValue],
        timeout: float,
    ) -> ExecutionEvidence:
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        head = required_str(args, "head")
        base = required_str(args, "base")
        targets = (
            f"github:repository:{owner}/{repo}",
            f"github:head-ref:{head}",
            f"github:base-ref:{base}",
        )
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls"
        try:
            response = self._transport.request(
                method="POST",
                path=path,
                body=json_bytes(pull_payload(args, operation_marker(context))),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            return self._unknown_transport(exc, external_resource_ids=targets)
        if response.status != 201:
            return self._execution_http_error(response, external_resource_ids=targets)
        parsed = parse_object(response.body)
        pull = pull_identity(parsed, owner=owner, repo=repo)
        if pull is None:
            return self._unknown_malformed(response, external_resource_ids=targets)
        if not pull_matches_intent(
            parsed,
            owner=owner,
            repo=repo,
            expected_head=head,
            expected_base=base,
        ):
            return self._unknown_inconsistent(
                response,
                "github.execute.pull_intent_inconsistent",
                external_resource_ids=targets,
            )
        operation_id, resource_id, number, html_url, state, head_sha = pull
        resources = targets + (resource_id, f"github:head-sha:{head_sha}")
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status=state,
                request_id=response.header("x-github-request-id"),
                external_operation_id=operation_id,
                external_resource_ids=resources,
                fields=json_from_plain(
                    {
                        "owner": owner,
                        "repo": repo,
                        "pull_number": number,
                        "head": head,
                        "base": base,
                    }
                ),
                raw_reference=html_url,
            ),
            error=None,
            external_operation_id=operation_id,
            external_resource_ids=resources,
        )

    def _execute_merge(
        self, args: dict[str, JsonValue], timeout: float
    ) -> ExecutionEvidence:
        owner = required_str(args, "owner")
        repo = required_str(args, "repo")
        number = required_int(args, "pull_number")
        head_sha = required_str(args, "head_sha").lower()
        resources = (pull_target(owner, repo, number), f"github:head-sha:{head_sha}")
        payload: dict[str, object] = {"sha": head_sha}
        merge_method = args.get("merge_method")
        if isinstance(merge_method, str):
            payload["merge_method"] = merge_method
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{number}/merge"
        try:
            response = self._transport.request(
                method="PUT",
                path=path,
                body=json_bytes(payload),
                timeout_seconds=timeout,
            )
        except Exception as exc:
            return self._unknown_transport(exc, external_resource_ids=resources)
        if response.status in {405, 409}:
            return ExecutionEvidence(
                outcome=EffectOutcome.NOT_APPLIED,
                evidence=self._evidence(
                    source=EvidenceSource.EXECUTION_RESPONSE,
                    status="not_merged",
                    request_id=response.header("x-github-request-id"),
                    external_operation_id=None,
                    external_resource_ids=resources,
                    fields=json_from_plain({"expected_head_sha": head_sha}),
                    raw_reference=f"https://github.com/{owner}/{repo}/pull/{number}",
                ),
                error=self._error(
                    ErrorKind.PROVIDER_REJECTED,
                    "github.merge.rejected",
                    retryable=False,
                    http=response.status,
                ),
                external_operation_id=None,
                external_resource_ids=resources,
            )
        if response.status != 200:
            return self._execution_http_error(response, external_resource_ids=resources)
        parsed = parse_object(response.body)
        if parsed is None or not isinstance(parsed.get("merged"), bool):
            return self._unknown_malformed(response, external_resource_ids=resources)
        if parsed["merged"] is False:
            return ExecutionEvidence(
                outcome=EffectOutcome.NOT_APPLIED,
                evidence=self._evidence(
                    source=EvidenceSource.EXECUTION_RESPONSE,
                    status="not_merged",
                    request_id=response.header("x-github-request-id"),
                    external_operation_id=None,
                    external_resource_ids=resources,
                    fields=json_from_plain({"expected_head_sha": head_sha}),
                    raw_reference=f"https://github.com/{owner}/{repo}/pull/{number}",
                ),
                error=self._error(
                    ErrorKind.PROVIDER_REJECTED,
                    "github.merge.not_applied",
                    retryable=False,
                    http=response.status,
                ),
                external_operation_id=None,
                external_resource_ids=resources,
            )
        merge_sha = parsed.get("sha")
        if not valid_git_sha(merge_sha):
            return self._unknown_malformed(response, external_resource_ids=resources)
        operation_id = f"github:merge:{merge_sha}"
        return ExecutionEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="merged",
                request_id=response.header("x-github-request-id"),
                external_operation_id=operation_id,
                external_resource_ids=resources,
                fields=json_from_plain(
                    {
                        "owner": owner,
                        "repo": repo,
                        "pull_number": number,
                        "expected_head_sha": head_sha,
                    }
                ),
                raw_reference=f"https://github.com/{owner}/{repo}/pull/{number}",
            ),
            error=None,
            external_operation_id=operation_id,
            external_resource_ids=resources,
        )

    def _request_verification(
        self, path: str
    ) -> GitHubHttpResponse | VerificationEvidence:
        try:
            return self._transport.request(
                method="GET",
                path=path,
                body=None,
                timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return self._verification_transport(exc)

    def _inconclusive_absence(
        self, response: GitHubHttpResponse
    ) -> VerificationEvidence:
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

    def _verify_comment(
        self, context: ProviderExecutionContext, request: VerificationRequest
    ) -> VerificationEvidence:
        target = parse_target_resource(
            request.external_resource_ids, "github:issue-target:"
        )
        if target is None:
            return self._verification_error(
                ErrorKind.VALIDATION,
                "github.verify.comment_target_missing",
                status="identity_missing",
            )
        owner, repo, number = target
        raw_comment = parse_prefixed_resource(
            request.external_resource_ids, "github:comment:"
        )
        comment_id: int | None = None
        if raw_comment is not None and ":" in raw_comment:
            try:
                comment_id = int(raw_comment.rsplit(":", 1)[1])
            except ValueError:
                comment_id = None
        path = (
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/comments/{comment_id}"
            if comment_id is not None
            else f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}/comments?per_page=100"
        )
        result = self._request_verification(path)
        if isinstance(result, VerificationEvidence):
            return result
        if result.status != 200:
            return self._verification_http_error(result)
        candidates = (
            [parse_object(result.body)]
            if comment_id is not None
            else parse_array(result.body)
        )
        marker = operation_marker(context)
        for candidate in candidates or []:
            comment = comment_identity(
                candidate, owner=owner, repo=repo, issue_number=number
            )
            if (
                comment is not None
                and isinstance(candidate, dict)
                and marker in str(candidate.get("body", ""))
            ):
                operation_id, resource_id, _, _, html_url = comment
                return VerificationEvidence(
                    outcome=EffectOutcome.APPLIED,
                    evidence=self._evidence(
                        source=EvidenceSource.CUSTOM,
                        status="created",
                        request_id=result.header("x-github-request-id"),
                        external_operation_id=operation_id,
                        external_resource_ids=(
                            issue_target(owner, repo, number),
                            resource_id,
                        ),
                        fields=json_from_plain({"marker_matched": True}),
                        raw_reference=html_url,
                    ),
                    error=None,
                )
        return self._inconclusive_absence(result)

    def _verify_label(self, request: VerificationRequest) -> VerificationEvidence:
        target = parse_target_resource(
            request.external_resource_ids, "github:issue-target:"
        )
        label = parse_prefixed_resource(request.external_resource_ids, "github:label:")
        if target is None or label is None:
            return self._verification_error(
                ErrorKind.VALIDATION,
                "github.verify.label_target_missing",
                status="identity_missing",
            )
        owner, repo, number = target
        result = self._request_verification(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/issues/{number}"
        )
        if isinstance(result, VerificationEvidence):
            return result
        if result.status != 200:
            return self._verification_http_error(result)
        parsed = parse_object(result.body)
        labels = parsed.get("labels") if parsed is not None else None
        if not isinstance(labels, list):
            return self._verification_error(
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.verify.malformed_response",
                status="malformed",
            )
        present = any(
            isinstance(item, dict) and item.get("name") == label for item in labels
        )
        return VerificationEvidence(
            outcome=EffectOutcome.APPLIED if present else EffectOutcome.NOT_APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.READ_BACK,
                status="present" if present else "absent",
                request_id=result.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=request.external_resource_ids,
                fields=json_from_plain({"label": label, "present": present}),
                raw_reference=f"https://github.com/{owner}/{repo}/issues/{number}",
            ),
            error=None,
        )

    def _pull_verification_target(
        self, request: VerificationRequest
    ) -> tuple[str, str, int | None, str | None, str | None] | None:
        pull = parse_target_resource(request.external_resource_ids, "github:pull:")
        repo_raw = parse_prefixed_resource(
            request.external_resource_ids, "github:repository:"
        )
        head = parse_prefixed_resource(
            request.external_resource_ids, "github:head-ref:"
        )
        base = parse_prefixed_resource(
            request.external_resource_ids, "github:base-ref:"
        )
        if pull is not None:
            owner, repo, number = pull
            return owner, repo, number, head, base
        if repo_raw is None or "/" not in repo_raw:
            return None
        owner, repo = repo_raw.split("/", 1)
        return owner, repo, None, head, base

    def _verify_pull(
        self, context: ProviderExecutionContext, request: VerificationRequest
    ) -> VerificationEvidence:
        target = self._pull_verification_target(request)
        if target is None:
            return self._verification_error(
                ErrorKind.VALIDATION,
                "github.verify.pull_target_missing",
                status="identity_missing",
            )
        owner, repo, number, head, base = target
        if head is None or base is None:
            return self._verification_error(
                ErrorKind.VALIDATION,
                "github.verify.pull_intent_missing",
                status="identity_missing",
            )
        if number is not None:
            path = (
                f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{number}"
            )
        else:
            query_head = head if ":" in head else f"{owner}:{head}"
            query = urlencode(
                {
                    "state": "all",
                    "head": query_head,
                    "base": base,
                    "per_page": "100",
                }
            )
            path = (
                f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls?{query}"
            )
        result = self._request_verification(path)
        if isinstance(result, VerificationEvidence):
            return result
        if result.status != 200:
            return self._verification_http_error(result)
        candidates = (
            [parse_object(result.body)]
            if number is not None
            else parse_array(result.body)
        )
        marker = operation_marker(context)
        for candidate in candidates or []:
            pull = pull_identity(
                candidate, owner=owner, repo=repo, expected_number=number
            )
            if pull is not None and not pull_matches_intent(
                candidate,
                owner=owner,
                repo=repo,
                expected_head=head,
                expected_base=base,
            ):
                if number is not None:
                    return self._verification_error(
                        ErrorKind.PROVIDER_INCONSISTENT,
                        "github.verify.pull_intent_inconsistent",
                        status="intent_inconsistent",
                    )
                continue
            if (
                pull is None
                or not isinstance(candidate, dict)
                or marker not in str(candidate.get("body", ""))
            ):
                continue
            operation_id, resource_id, _, html_url, state, head_sha = pull
            outcome = (
                EffectOutcome.NOT_APPLIED
                if request.target is VerificationTarget.COMPENSATION
                and state != "closed"
                else EffectOutcome.APPLIED
            )
            return VerificationEvidence(
                outcome=outcome,
                evidence=self._evidence(
                    source=EvidenceSource.CUSTOM,
                    status=state,
                    request_id=result.header("x-github-request-id"),
                    external_operation_id=operation_id,
                    external_resource_ids=request.external_resource_ids
                    + (resource_id, f"github:head-sha:{head_sha}"),
                    fields=json_from_plain({"marker_matched": True}),
                    raw_reference=html_url,
                ),
                error=None,
            )
        return self._inconclusive_absence(result)

    def _verify_merge(self, request: VerificationRequest) -> VerificationEvidence:
        target = parse_target_resource(request.external_resource_ids, "github:pull:")
        expected_head = parse_prefixed_resource(
            request.external_resource_ids, "github:head-sha:"
        )
        if target is None or expected_head is None:
            return self._verification_error(
                ErrorKind.VALIDATION,
                "github.verify.merge_target_missing",
                status="identity_missing",
            )
        owner, repo, number = target
        result = self._request_verification(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{number}"
        )
        if isinstance(result, VerificationEvidence):
            return result
        if result.status != 200:
            return self._verification_http_error(result)
        parsed = parse_object(result.body)
        pull = pull_identity(parsed, owner=owner, repo=repo, expected_number=number)
        if pull is None or parsed is None:
            return self._verification_error(
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.verify.malformed_response",
                status="malformed",
            )
        actual_head = pull[5].lower()
        merged = parsed.get("merged")
        if not isinstance(merged, bool):
            return self._verification_error(
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.verify.malformed_response",
                status="malformed",
            )
        if actual_head != expected_head.lower():
            return self._verification_error(
                ErrorKind.PROVIDER_INCONSISTENT,
                "github.verify.merge_head_changed",
                status="head_changed",
            )
        outcome = EffectOutcome.APPLIED if merged else EffectOutcome.NOT_APPLIED
        return VerificationEvidence(
            outcome=outcome,
            evidence=self._evidence(
                source=EvidenceSource.READ_BACK,
                status="merged" if merged else "not_merged",
                request_id=result.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=request.external_resource_ids,
                fields=json_from_plain(
                    {"expected_head_sha": expected_head, "head_matched": True}
                ),
                raw_reference=pull[3],
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
        pull_resource = parse_target_resource(
            tuple(
                resource
                for evidence in request.original_evidence
                for resource in evidence.external_resource_ids
            ),
            "github:pull:",
        )
        if pull_resource is not None:
            return self._close_pull_request(pull_resource)
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

    def _close_pull_request(
        self, resource: tuple[str, str, int]
    ) -> CompensationEvidence:
        owner, repo, number = resource
        path = f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{number}"
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
        pull = pull_identity(
            parse_object(response.body), owner=owner, repo=repo, expected_number=number
        )
        if pull is None or pull[4] != "closed":
            return self._compensation_error(
                EffectOutcome.UNKNOWN,
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.compensation.malformed_response",
                status="malformed",
                http=response.status,
            )
        operation_id, resource_id, _, html_url, state, _ = pull
        return CompensationEvidence(
            outcome=EffectOutcome.APPLIED,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status=state,
                request_id=response.header("x-github-request-id"),
                external_operation_id=operation_id,
                external_resource_ids=(resource_id,),
                fields=json_from_plain(
                    {"mitigation": "closed_pull_request", "rollback": False}
                ),
                raw_reference=html_url,
            ),
            error=None,
            external_operation_id=operation_id,
        )

    def _timeout(self, context: ProviderExecutionContext) -> float | None:
        if context.deadline is None:
            return _DEFAULT_TIMEOUT_SECONDS
        remaining = (context.deadline.value - self._clock.now().value).total_seconds()
        return remaining if remaining > 0 else None

    def _execution_http_error(
        self,
        response: GitHubHttpResponse,
        *,
        external_resource_ids: tuple[str, ...] = (),
    ) -> ExecutionEvidence:
        kind, code, retryable, known = classify_http(response)
        outcome = EffectOutcome.NOT_APPLIED if known else EffectOutcome.UNKNOWN
        return ExecutionEvidence(
            outcome=outcome,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="rejected" if known else "ambiguous_http_failure",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=external_resource_ids,
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
            external_resource_ids=external_resource_ids,
        )

    def _unknown_inconsistent(
        self,
        response: GitHubHttpResponse,
        code: str,
        *,
        external_resource_ids: tuple[str, ...],
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="intent_inconsistent",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=external_resource_ids,
                fields=_EMPTY,
                raw_reference=None,
            ),
            error=self._error(
                ErrorKind.PROVIDER_INCONSISTENT,
                code,
                http=response.status,
            ),
            external_operation_id=None,
            external_resource_ids=external_resource_ids,
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

    def _unknown_transport(
        self,
        exc: Exception,
        *,
        external_resource_ids: tuple[str, ...] = (),
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="transport_ambiguous",
                request_id=None,
                external_operation_id=None,
                external_resource_ids=external_resource_ids,
                fields=json_from_plain({"exception_type": type(exc).__name__}),
                raw_reference=None,
            ),
            error=self._error(
                ErrorKind.TRANSIENT_TRANSPORT,
                "github.transport.ambiguous",
                retryable=True,
            ),
            external_operation_id=None,
            external_resource_ids=external_resource_ids,
        )

    def _unknown_malformed(
        self,
        response: GitHubHttpResponse,
        *,
        external_resource_ids: tuple[str, ...] = (),
    ) -> ExecutionEvidence:
        return ExecutionEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=self._evidence(
                source=EvidenceSource.EXECUTION_RESPONSE,
                status="malformed",
                request_id=response.header("x-github-request-id"),
                external_operation_id=None,
                external_resource_ids=external_resource_ids,
                fields=_EMPTY,
                raw_reference=None,
            ),
            error=self._error(
                ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                "github.execute.malformed_response",
                http=response.status,
            ),
            external_operation_id=None,
            external_resource_ids=external_resource_ids,
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
