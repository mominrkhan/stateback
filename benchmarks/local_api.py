"""Isolated production-path ASGI assembly for Phase 17 measurements only."""

from __future__ import annotations

import os

from fastapi import FastAPI

from stateback.api import create_app
from stateback.application import (
    ApplicationService,
    AuthenticatedIdentity,
    Role,
    StaticTokenAuthenticator,
)
from stateback.domain.enums import PrincipalType
from stateback.domain.refs import PrincipalRef
from stateback.persistence.engine import create_engine_from_env, session_factory
from stateback.policy import AllowAllPolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import SystemClock
from stateback.runtime.service import SynchronousRuntime


def build_app() -> FastAPI:
    token = os.environ.get("STATEBACK_BENCH_SERVER_TOKEN")
    if not token:
        raise RuntimeError("STATEBACK_BENCH_SERVER_TOKEN is required")
    clock = SystemClock()
    registry = CapabilityRegistry()
    registry.register(ReferenceAdapter(store=ReferenceStore(), clock=clock))
    factory = session_factory(create_engine_from_env())
    runtime = SynchronousRuntime(
        session_factory=factory,
        registry=registry,
        policy_engine=AllowAllPolicyEngine(),
        clock=clock,
    )
    service = ApplicationService(session_factory=factory, runtime=runtime)
    identity = AuthenticatedIdentity(
        principal=PrincipalRef(
            type=PrincipalType.OPERATOR,
            id="phase17-benchmark",
            display_name="Phase 17 Benchmark",
        ),
        roles=frozenset({Role.CALLER, Role.READER, Role.OPERATOR}),
    )
    return create_app(
        service=service,
        authenticator=StaticTokenAuthenticator(identities_by_token={token: identity}),
    )


app = build_app()
