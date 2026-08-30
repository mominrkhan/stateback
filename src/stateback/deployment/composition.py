"""One fail-closed composition of canonical services for release processes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
from stateback.providers.github.demo_fault import OperationScopedLostResponseAdapter
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


def build_services(
    *,
    require_auth: bool,
    execute_providers: bool,
    development_demo_arm_directory: Path | None = None,
) -> Services:
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
    if execute_providers:
        github_token = read_secret_file("STATEBACK_GITHUB_TOKEN_FILE")
        github_configured = github_token is not None and bool(github_token.strip())
        github_adapter = GitHubAdapter.from_token(token=github_token, clock=clock)
        github = (
            github_adapter
            if development_demo_arm_directory is None
            else OperationScopedLostResponseAdapter(
                delegate=github_adapter,
                arm_directory=development_demo_arm_directory,
                clock=clock,
            )
        )
    else:
        github_configured = boolean_env("STATEBACK_GITHUB_CONFIGURED")
        github = GitHubAdapter.for_validation(
            credential_configured=github_configured,
            clock=clock,
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
        configured_providers=(
            frozenset({"github"}) if github_configured else frozenset()
        ),
    )
    return Services(
        session_factory=factory,
        authenticator=authenticator,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        application=application,
    )
