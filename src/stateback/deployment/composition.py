"""One fail-closed composition of canonical services for release processes."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class Services:
    session_factory: sessionmaker[Session]
    authenticator: StaticTokenAuthenticator | None
    runtime: SynchronousRuntime
    recovery: RecoveryService
    compensation: CompensationService
    application: ApplicationService


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
    )
    return Services(
        session_factory=factory,
        authenticator=authenticator,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        application=application,
    )
