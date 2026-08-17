from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    ExecuteCompensationCommand,
    OperatorCompensationCommand,
    RecoverCompensationCommand,
    ScanCompensationCommand,
    StartCompensationCommand,
)
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.service import CompensationService
from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    AttemptState,
    EffectOutcome,
    ErrorKind,
    OperationState,
    PolicyVerdict,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import IntentEnvelope, operation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyDecision, PolicyObligations
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import unit_of_work
from stateback.policy import AllowAllPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_PROVIDER_KEY
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from stateback.transitions.commands import (
    ClaimExecution,
    CreateOperation,
    ExecutionNotAppliedFail,
    PolicyAllow,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.service import TransitionService
from tests.integration.compensation.idseq import (
    IdSeq,
    SeqCompensationIds,
    compensation_ids,
)
from tests.integration.recovery.conftest import make_recovery
from tests.integration.runtime.conftest import JOURNAL_TABLES, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids
from tests.unit.domain.fixtures import REQUESTER, RISK, TS

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


@pytest.fixture
def compensation(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> CompensationService:
    return CompensationService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
    )


def rebuild_compensation(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    *,
    crash_after: CompensationCrashPoint | None = None,
) -> CompensationService:
    return CompensationService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
        crash_after=crash_after,
    )


def make_start(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    automatic: bool = False,
    actor: PrincipalRef | None = None,
) -> StartCompensationCommand:
    return StartCompensationCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=compensation_ids(seq),
        actor=actor,
        correlation_id=None,
        automatic=automatic,
    )


def make_execute(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    actor: PrincipalRef | None = None,
) -> ExecuteCompensationCommand:
    return ExecuteCompensationCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=compensation_ids(seq),
        actor=actor,
        correlation_id=None,
    )


def make_recover(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    actor: PrincipalRef | None = None,
) -> RecoverCompensationCommand:
    return RecoverCompensationCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=compensation_ids(seq),
        actor=actor,
        correlation_id=None,
    )


def make_scan(seq: IdSeq, *, limit: int | None = None) -> ScanCompensationCommand:
    return ScanCompensationCommand(
        ids_for=SeqCompensationIds(seq),
        actor=None,
        correlation_id=None,
        limit=limit,
    )


def make_operator(
    seq: IdSeq,
    operation_id: OpaqueId,
    expected_version: int,
    *,
    actor: PrincipalRef,
    reason_code: str = "operator_action",
) -> OperatorCompensationCommand:
    return OperatorCompensationCommand(
        operation_id=operation_id,
        expected_version=expected_version,
        ids=compensation_ids(seq),
        actor=actor,
        correlation_id=None,
        reason_code=reason_code,
    )


def run_to_succeeded(runtime: SynchronousRuntime, seq: IdSeq) -> Operation:
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    return result.operation


def run_to_succeeded_via_recovery(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    seq: IdSeq,
) -> Operation:
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    return recovered.operation


def load_compensation(
    uow_factory: sessionmaker[Session], compensation_id: OpaqueId
) -> Compensation | None:
    with unit_of_work(uow_factory) as uow:
        return uow.compensations.get(compensation_id)


def load_compensation_attempts(
    uow_factory: sessionmaker[Session], compensation_id: OpaqueId
) -> list[CompensationAttempt]:
    with unit_of_work(uow_factory) as uow:
        return uow.compensation_attempts.list_for_compensation(compensation_id)


def load_operation(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> Operation:
    with unit_of_work(uow_factory) as uow:
        op = uow.operations.get(operation_id)
        assert op is not None
        return op


def _make_intent(effect: EffectRef, resource_id: str) -> IntentEnvelope:
    return IntentEnvelope.from_parts(
        effect=effect,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"resource_id": resource_id}),
        arguments_ref=None,
        requester=REQUESTER,
        requested_at=TS,
        metadata=(),
    )


def build_failed_operation_with_artifact(
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
    *,
    effect: EffectRef = EFFECT_MUTATE_PROVIDER_KEY,
    external_operation_id: str | None = "ext-failed-1",
    external_resource_ids: tuple[str, ...] = (),
    error_kind: ErrorKind = ErrorKind.PROVIDER_REJECTED,
    obligations: PolicyObligations | None = None,
) -> Operation:
    """Build a `FAILED` operation whose latest original attempt carries an
    external artifact (§11.6 `has_external_artifact`), driven directly through
    `TransitionService` since the reference adapter never returns ids for a
    `NOT_APPLIED` outcome (PHASE_7.md §12.4 `test_failed_with_artifact_*`).
    """
    service = TransitionService()
    op_id = seq.next()
    operation = Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=op_id,
        state=OperationState.PENDING_POLICY,
        version=1,
        intent=_make_intent(effect, f"res-{op_id.value[-4:]}"),
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(op_id),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )
    with unit_of_work(uow_factory) as uow:
        created = service.apply(
            uow,
            CreateOperation(
                kind=TransitionKind.CREATE_OPERATION,
                operation=operation,
                occurred_at=TS,
                actor=REQUESTER,
                correlation_id=None,
                reason_code="created",
                created_audit_event_id=seq.next(),
            ),
        )
    assert created.operation is not None
    op = created.operation

    policy = PolicyDecision(
        contract_version=CONTRACT_VERSION,
        policy_decision_id=seq.next(),
        operation_id=op.operation_id,
        operation_version=op.version,
        intent_digest=op.intent.intent_digest,
        verdict=PolicyVerdict.ALLOW,
        reason_codes=("allow",),
        explanation=None,
        obligations=(
            obligations if obligations is not None else PHASE5_DEFAULT_OBLIGATIONS
        ),
        policy_revision=PHASE5_POLICY_REVISION,
        evaluated_at=TS,
    )
    with unit_of_work(uow_factory) as uow:
        allowed = service.apply(
            uow,
            PolicyAllow(
                kind=TransitionKind.POLICY_ALLOW,
                operation_id=op.operation_id,
                expected_version=op.version,
                occurred_at=TS,
                actor=REQUESTER,
                correlation_id=None,
                reason_code="allow",
                transition_audit_event_id=seq.next(),
                policy_decision=policy,
                policy_audit_event_id=seq.next(),
                outbox_event_id=seq.next(),
            ),
        )
    assert allowed.operation is not None
    op = allowed.operation

    started = ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=seq.next(),
        operation_id=op.operation_id,
        attempt_number=1,
        state=AttemptState.STARTED,
        started_at=TS,
        completed_at=None,
        provider_idempotency_key="key-1",
        external_operation_id=None,
        external_resource_ids=(),
        outcome=None,
        evidence=None,
        error=None,
        correlation_id=None,
    )
    with unit_of_work(uow_factory) as uow:
        claimed = service.apply(
            uow,
            ClaimExecution(
                kind=TransitionKind.CLAIM_EXECUTION,
                operation_id=op.operation_id,
                expected_version=op.version,
                occurred_at=TS,
                actor=None,
                correlation_id=None,
                reason_code="claimed",
                transition_audit_event_id=seq.next(),
                attempt=started,
                attempt_audit_event_id=seq.next(),
            ),
        )
    assert claimed.operation is not None
    op = claimed.operation

    completed = ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=started.attempt_id,
        operation_id=started.operation_id,
        attempt_number=started.attempt_number,
        state=AttemptState.COMPLETED,
        started_at=started.started_at,
        completed_at=TS,
        provider_idempotency_key=started.provider_idempotency_key,
        external_operation_id=external_operation_id,
        external_resource_ids=external_resource_ids,
        outcome=EffectOutcome.NOT_APPLIED,
        evidence=None,
        error=NormalizedError(
            contract_version=CONTRACT_VERSION,
            kind=error_kind,
            code="ref.rejected.partial",
            message="provider rejected after partial accept",
            retryable_infrastructure=False,
            provider_http_status=400,
            provider_error_code=None,
            retry_after_seconds=None,
            details=json_from_plain({}),
        ),
        correlation_id=None,
    )
    with unit_of_work(uow_factory) as uow:
        failed = service.apply(
            uow,
            ExecutionNotAppliedFail(
                kind=TransitionKind.EXECUTION_NOT_APPLIED_FAIL,
                operation_id=op.operation_id,
                expected_version=op.version,
                occurred_at=TS,
                actor=None,
                correlation_id=None,
                reason_code="not_applied",
                transition_audit_event_id=seq.next(),
                completed_attempt=completed,
                evidence_audit_event_id=seq.next(),
            ),
        )
    assert failed.operation is not None
    return failed.operation
