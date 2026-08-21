"""One fail-closed composition of canonical services for release processes."""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from stateback.application import ApplicationService, StaticTokenAuthenticator
from stateback.approval import ApprovalService, ConfiguredApproverAuthorizer
from stateback.compensation import CompensationService
from stateback.deployment.config import (
    boolean_env,
    load_auth,
    load_policy,
    read_secret_file,
)
from stateback.persistence import create_engine_from_env, session_factory
from stateback.providers.github import GitHubAdapter
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery import RecoveryService
from stateback.runtime import SynchronousRuntime
from stateback.runtime.clock import SystemClock
from stateback.semantic import AuditSummaryService, OllamaSemanticModel


@dataclass(frozen=True, slots=True)
class Services:
    session_factory: sessionmaker[Session]
    authenticator: StaticTokenAuthenticator | None
    runtime: SynchronousRuntime
    recovery: RecoveryService
    compensation: CompensationService
    application: ApplicationService


def _semantic_service() -> AuditSummaryService | None:
    url = os.environ.get("STATEBACK_SEMANTIC_OLLAMA_URL")
    model = os.environ.get("STATEBACK_SEMANTIC_OLLAMA_MODEL")
    timeout = os.environ.get("STATEBACK_SEMANTIC_OLLAMA_TIMEOUT")
    configured = (url, model, timeout)
    if not any(value is not None for value in configured):
        return None
    if not all(value is not None and value.strip() for value in configured):
        raise RuntimeError(
            "STATEBACK_SEMANTIC_OLLAMA_URL, _MODEL, and _TIMEOUT must be set together"
        )
    assert url is not None and model is not None and timeout is not None
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "STATEBACK_SEMANTIC_OLLAMA_TIMEOUT must be a number"
        ) from exc
    try:
        model_client = OllamaSemanticModel(
            base_url=url, model=model, timeout_seconds=timeout_seconds
        )
    except ValueError as exc:
        raise RuntimeError("semantic Ollama configuration is invalid") from exc
    return AuditSummaryService(semantic_model=model_client)


def build_services(*, require_auth: bool, execute_providers: bool) -> Services:
    clock = SystemClock()
    factory = session_factory(create_engine_from_env())
    policy = load_policy()
    if require_auth:
        authenticator, approver_authorizer = load_auth()
    else:
        # Workers never authenticate callers, but ApprovalService is part of the
        # shared composition. An empty authorizer cannot grant an approval.
        authenticator = None
        approver_authorizer = ConfiguredApproverAuthorizer(
            allowed_principals=frozenset()
        )
    registry = CapabilityRegistry()
    github = (
        GitHubAdapter.from_token(
            token=read_secret_file("STATEBACK_GITHUB_TOKEN_FILE"), clock=clock
        )
        if execute_providers
        else GitHubAdapter.for_validation(
            credential_configured=boolean_env("STATEBACK_GITHUB_CONFIGURED"),
            clock=clock,
        )
    )
    registry.register(github)
    runtime = SynchronousRuntime(
        session_factory=factory,
        registry=registry,
        policy_engine=policy,
        clock=clock,
    )
    recovery = RecoveryService(session_factory=factory, registry=registry, clock=clock)
    compensation = CompensationService(
        session_factory=factory, registry=registry, clock=clock
    )
    approvals = ApprovalService(
        session_factory=factory,
        authorizer=approver_authorizer,
        clock=clock,
    )
    application = ApplicationService(
        session_factory=factory,
        runtime=runtime,
        approvals=approvals,
        recovery=recovery,
        compensation=compensation,
        registry=registry,
        semantic_summaries=_semantic_service(),
    )
    return Services(
        session_factory=factory,
        authenticator=authenticator,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        application=application,
    )
