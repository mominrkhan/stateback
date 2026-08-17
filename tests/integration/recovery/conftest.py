from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import unit_of_work
from stateback.policy import AllowAllPolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.commands import RecoveryCommand
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.idseq import IdSeq, recovery_ids
from tests.integration.runtime.conftest import JOURNAL_TABLES, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids
from tests.unit.domain.fixtures import TS

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


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


@pytest.fixture
def recovery(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> RecoveryService:
    return RecoveryService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
    )


def make_recovery(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
) -> RecoveryCommand:
    return RecoveryCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=recovery_ids(seq),
        actor=None,
        correlation_id=None,
    )


def rebuild_recovery(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    *,
    crash_after: RecoveryCrashPoint | None = None,
) -> RecoveryService:
    return RecoveryService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
        crash_after=crash_after,
    )


def run_unknown_timeout(runtime: SynchronousRuntime, seq: IdSeq) -> Operation:
    adapter = runtime._registry.adapter_for(EFFECT_MUTATE_PROVIDER_KEY)
    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    return result.operation


def load_verifications(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[tuple[VerificationRequest, VerificationResult | None]]:
    with unit_of_work(uow_factory) as uow:
        return uow.verifications.list_for_operation(operation_id)
