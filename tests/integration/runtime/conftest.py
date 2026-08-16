from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyDecision
from stateback.domain.refs import EffectRef
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import unit_of_work
from stateback.policy import AllowAllPolicyEngine
from stateback.policy.protocol import PolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import (
    PHASE5_ENVIRONMENT,
    ExecuteCommand,
    RecoverCommand,
    SubmitCommand,
    SynchronousRuntime,
)
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.ids import ExecuteIds, RecoverIds, SubmitIds
from tests.integration.runtime.idseq import (
    IdSeq,
    execute_ids,
    recover_ids,
    submit_ids,
)
from tests.unit.domain.fixtures import REQUESTER, TS
from tests.unit.runtime.fixtures import ARGUMENTS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

JOURNAL_TABLES = (
    "reconciliation_decisions",
    "outbox_events",
    "audit_events",
    "compensation_attempts",
    "compensations",
    "verifications",
    "approvals",
    "policy_decisions",
    "execution_attempts",
    "operations",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    return os.environ["STATEBACK_DATABASE_URL"]


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine_from_url(database_url)
    inspector = inspect(engine)
    missing = [name for name in JOURNAL_TABLES if not inspector.has_table(name)]
    if missing:
        engine.dispose()
        pytest.fail(
            "journal tables missing; run `uv run alembic upgrade head`: "
            + ", ".join(missing)
        )
    yield engine
    engine.dispose()


@pytest.fixture
def uow_factory(engine: Engine) -> sessionmaker[Session]:
    return session_factory(engine)


@pytest.fixture(autouse=True)
def truncate_journal(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                TRUNCATE TABLE
                  reconciliation_decisions,
                  outbox_events,
                  audit_events,
                  compensation_attempts,
                  compensations,
                  verifications,
                  approvals,
                  policy_decisions,
                  execution_attempts,
                  operations
                RESTART IDENTITY CASCADE
                """
            )
        )


@pytest.fixture
def store() -> ReferenceStore:
    return ReferenceStore()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(TS)


@pytest.fixture
def adapter(store: ReferenceStore, clock: FixedClock) -> ReferenceAdapter:
    return ReferenceAdapter(store=store, clock=clock)


@pytest.fixture
def registry(adapter: ReferenceAdapter) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(adapter)
    return registry


@pytest.fixture
def seq() -> IdSeq:
    return IdSeq()


@pytest.fixture
def runtime(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> SynchronousRuntime:
    return SynchronousRuntime(
        session_factory=uow_factory,
        registry=registry,
        policy_engine=AllowAllPolicyEngine(),
        clock=clock,
    )


def make_submit(
    seq: IdSeq,
    *,
    ids: SubmitIds | None = None,
    effect: EffectRef = EFFECT_MUTATE_PROVIDER_KEY,
    arguments: JsonValue = ARGUMENTS,
    metadata: tuple[tuple[str, str], ...] = (),
) -> SubmitCommand:
    return SubmitCommand(
        effect=effect,
        arguments=arguments,
        requester=REQUESTER,
        metadata=metadata,
        ids=ids if ids is not None else submit_ids(seq),
        correlation_id=None,
        deployment_environment=PHASE5_ENVIRONMENT,
    )


def make_execute(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    ids: ExecuteIds | None = None,
) -> ExecuteCommand:
    return ExecuteCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=ids if ids is not None else execute_ids(seq),
        actor=REQUESTER,
        correlation_id=None,
    )


def make_recover(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    ids: RecoverIds | None = None,
) -> RecoverCommand:
    return RecoverCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=ids if ids is not None else recover_ids(seq),
        actor=None,
        correlation_id=None,
    )


def load_operation(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> Operation:
    with unit_of_work(uow_factory) as uow:
        op = uow.operations.get(operation_id)
        assert op is not None
        return op


def load_attempts(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[ExecutionAttempt]:
    with unit_of_work(uow_factory) as uow:
        return uow.attempts.list_for_operation(operation_id)


def load_policies(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[PolicyDecision]:
    with unit_of_work(uow_factory) as uow:
        return uow.policy_decisions.list_for_operation(operation_id)


def load_audits(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[AuditEvent]:
    with unit_of_work(uow_factory) as uow:
        return uow.audit_events.list_for_operation(operation_id)


def load_outbox(uow_factory: sessionmaker[Session]) -> list[OutboxEvent]:
    with unit_of_work(uow_factory) as uow:
        return uow.outbox_events.list_pending_for_claim(100)


def rebuild_runtime(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    *,
    policy_engine: PolicyEngine | None = None,
    crash_after: RuntimeCrashPoint | None = None,
) -> SynchronousRuntime:
    engine = AllowAllPolicyEngine() if policy_engine is None else policy_engine
    return SynchronousRuntime(
        session_factory=uow_factory,
        registry=registry,
        policy_engine=engine,
        clock=clock,
        crash_after=crash_after,
    )
