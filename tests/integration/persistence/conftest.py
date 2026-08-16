from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    ArgumentsMode,
    AttemptState,
    AuditEventType,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    EvidenceSource,
    OperationState,
    OutboxState,
    PolicyVerdict,
    VerificationTarget,
    WorkCommand,
)
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import (
    compensation_idempotency_identity,
    operation_idempotency_identity,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval, PolicyDecision, PolicyObligations
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import UnitOfWork, unit_of_work
from tests.unit.domain.fixtures import (
    APPROVAL_ID,
    ATTEMPT_ID,
    AUDIT_ID,
    COMP_ATTEMPT_ID,
    COMP_ID,
    EFFECT,
    LATER,
    OP_ID,
    OUTBOX_ID,
    POLICY_ID,
    REQUESTER,
    RISK,
    TS,
    VERIFY_ID,
    make_intent,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

OP_ID_2 = OpaqueId(value="00000000-0000-4000-8000-00000000000b")
ATTEMPT_ID_2 = OpaqueId(value="00000000-0000-4000-8000-00000000000c")
AUDIT_ID_2 = OpaqueId(value="00000000-0000-4000-8000-00000000000d")
OUTBOX_ID_2 = OpaqueId(value="00000000-0000-4000-8000-00000000000e")
RECONCILE_ID = OpaqueId(value="00000000-0000-4000-8000-00000000000f")

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
    url = os.environ["STATEBACK_DATABASE_URL"]
    return url


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


def make_operation(
    *,
    operation_id: OpaqueId = OP_ID,
    state: OperationState = OperationState.PENDING_POLICY,
    version: int = 1,
) -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=operation_id,
        state=state,
        version=version,
        intent=make_intent(),
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(operation_id),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )


def make_started_attempt(
    *,
    attempt_id: OpaqueId = ATTEMPT_ID,
    operation_id: OpaqueId = OP_ID,
    attempt_number: int = 1,
) -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=attempt_id,
        operation_id=operation_id,
        attempt_number=attempt_number,
        state=AttemptState.STARTED,
        started_at=TS,
        completed_at=None,
        provider_idempotency_key=None,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=None,
        evidence=None,
        error=None,
        correlation_id=None,
    )


def make_unknown_evidence() -> ProviderEvidence:
    return ProviderEvidence(
        source=EvidenceSource.EXECUTION_RESPONSE,
        provider="reference",
        observed_at=LATER,
        provider_status=None,
        provider_request_id=None,
        external_operation_id=None,
        external_resource_ids=(),
        evidence_fields=json_from_plain({"observed": "timeout"}),
        raw_reference=None,
    )


def make_completed_unknown_attempt(
    *,
    attempt_id: OpaqueId = ATTEMPT_ID,
    operation_id: OpaqueId = OP_ID,
    attempt_number: int = 1,
) -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=attempt_id,
        operation_id=operation_id,
        attempt_number=attempt_number,
        state=AttemptState.COMPLETED,
        started_at=TS,
        completed_at=LATER,
        provider_idempotency_key=None,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=EffectOutcome.UNKNOWN,
        evidence=make_unknown_evidence(),
        error=None,
        correlation_id=None,
    )


def make_policy(
    *,
    operation_id: OpaqueId = OP_ID,
    intent_digest: str | None = None,
) -> PolicyDecision:
    digest = intent_digest if intent_digest is not None else make_intent().intent_digest
    return PolicyDecision(
        contract_version=CONTRACT_VERSION,
        policy_decision_id=POLICY_ID,
        operation_id=operation_id,
        operation_version=1,
        intent_digest=digest,
        verdict=PolicyVerdict.REQUIRE_APPROVAL,
        reason_codes=("approval_required",),
        explanation=None,
        obligations=PolicyObligations(
            require_verification=True,
            max_automatic_execution_attempts=3,
            max_automatic_recovery_attempts=3,
            automatic_compensation_allowed=False,
            operator_reason_required=False,
            approval_expires_at=None,
        ),
        policy_revision="policy-v1",
        evaluated_at=TS,
    )


def make_approval(
    *,
    state: ApprovalState = ApprovalState.PENDING,
) -> Approval:
    return Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=APPROVAL_ID,
        operation_id=OP_ID,
        operation_version=1,
        intent_digest=make_intent().intent_digest,
        policy_decision_id=POLICY_ID,
        state=state,
        requested_at=TS,
        expires_at=None,
        decided_at=None if state is ApprovalState.PENDING else LATER,
        decided_by=None if state is ApprovalState.PENDING else REQUESTER,
        reason=None if state is ApprovalState.PENDING else "approved",
    )


def make_verification_request() -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OP_ID,
        operation_version=1,
        target=VerificationTarget.ORIGINAL_EFFECT,
        target_attempt_id=ATTEMPT_ID,
        effect=EFFECT,
        external_operation_id=None,
        external_resource_ids=(),
        idempotency_identity="sb:v1:verify:" + VERIFY_ID.value,
        provider_evidence_refs=(),
        requested_at=TS,
    )


def make_verification_result() -> VerificationResult:
    return VerificationResult(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        outcome=EffectOutcome.UNKNOWN,
        evidence=make_unknown_evidence(),
        error=None,
        completed_at=LATER,
    )


def make_compensation() -> Compensation:
    return Compensation(
        contract_version=CONTRACT_VERSION,
        compensation_id=COMP_ID,
        original_operation_id=OP_ID,
        kind=CompensationKind.EXACT,
        state=CompensationState.PENDING,
        version=1,
        intent_digest=make_intent().intent_digest,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"reason": "undo"}),
        arguments_ref=None,
        idempotency_identity=compensation_idempotency_identity(COMP_ID),
        requested_by=REQUESTER,
        policy_decision_id=None,
        created_at=TS,
        updated_at=TS,
    )


def make_compensation_attempt(
    *,
    compensation_attempt_id: OpaqueId = COMP_ATTEMPT_ID,
    attempt_number: int = 1,
    state: AttemptState = AttemptState.STARTED,
) -> CompensationAttempt:
    completed = state is AttemptState.COMPLETED
    return CompensationAttempt(
        contract_version=CONTRACT_VERSION,
        compensation_attempt_id=compensation_attempt_id,
        compensation_id=COMP_ID,
        attempt_number=attempt_number,
        state=state,
        started_at=TS,
        completed_at=LATER if completed else None,
        provider_idempotency_key=None,
        external_operation_id=None,
        outcome=EffectOutcome.UNKNOWN if completed else None,
        evidence=make_unknown_evidence() if completed else None,
        error=None,
    )


def make_audit(
    *,
    audit_event_id: OpaqueId = AUDIT_ID,
    sequence: int = 1,
    event_type: AuditEventType = AuditEventType.OPERATION_CREATED,
    from_state: OperationState | None = None,
    to_state: OperationState | None = None,
) -> AuditEvent:
    return AuditEvent(
        contract_version=CONTRACT_VERSION,
        audit_event_id=audit_event_id,
        operation_id=OP_ID,
        sequence=sequence,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        operation_version=1,
        actor=REQUESTER,
        reason_code="created",
        data=json_from_plain({"note": "created"}),
        correlation_id=None,
        created_at=TS,
    )


def make_outbox(
    *,
    event_id: OpaqueId = OUTBOX_ID,
    state: OutboxState = OutboxState.PENDING,
) -> OutboxEvent:
    return OutboxEvent(
        contract_version=CONTRACT_VERSION,
        event_id=event_id,
        state=state,
        aggregate_type="operation",
        aggregate_id=OP_ID,
        operation_version=1,
        command=WorkCommand.EXECUTE,
        created_at=TS,
        published_at=None if state is OutboxState.PENDING else LATER,
        correlation_id=None,
    )


def persist_operation(
    uow_factory: sessionmaker[Session], operation: Operation | None = None
) -> Operation:
    stored = make_operation() if operation is None else operation
    with unit_of_work(uow_factory) as uow:
        uow.operations.insert(stored)
    return stored


def open_uow(uow_factory: sessionmaker[Session]) -> UnitOfWork:
    return UnitOfWork(uow_factory())
