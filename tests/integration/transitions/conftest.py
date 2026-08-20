from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    ArgumentsMode,
    AttemptState,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    EvidenceSource,
    IdempotencyMode,
    OperationState,
    PolicyVerdict,
    PrincipalType,
    ReconciliationAction,
    VerificationTarget,
)
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import (
    compensation_idempotency_identity,
    operation_idempotency_identity,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision, PolicyObligations
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.domain.refs import PrincipalRef
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.types import StoredReconciliationDecision
from stateback.persistence.uow import unit_of_work
from stateback.transitions.commands import (
    ApprovalGrant,
    ApprovalReject,
    CancelAwaitingApproval,
    CancelPendingPolicy,
    CancelReady,
    ClaimCompensationExecution,
    ClaimExecution,
    CompensationApplied,
    CompensationEscalate,
    CompensationFailedEscalate,
    CompensationFailedRetry,
    CompensationOutcomeFailed,
    CompensationOutcomeUnknown,
    CompensationUnknownApplied,
    CompensationUnknownEscalate,
    CompensationUnknownFailed,
    CompensationUnknownRetry,
    CreateOperation,
    ExecutionApplied,
    ExecutionMessagingRecoveryExhausted,
    ExecutionNotAppliedFail,
    ExecutionNotAppliedRetry,
    ExecutionRequireVerification,
    ExecutionUnknown,
    FailedStartCompensation,
    ManualSafeRetry,
    ManualStartCompensation,
    ManualStartVerification,
    PolicyAllow,
    PolicyDeny,
    PolicyRequireApproval,
    ReadyMessagingRecoveryExhausted,
    SucceededStartCompensation,
    TransitionCommand,
    UnknownEscalate,
    UnknownReconcileApplied,
    UnknownReconcileNotApplied,
    UnknownSafeRetry,
    UnknownStartVerification,
    VerificationApplied,
    VerificationEscalate,
    VerificationInconclusive,
    VerificationNotAppliedFail,
    VerificationNotAppliedRetry,
)
from stateback.transitions.kinds import (
    KIND_TO_EDGE,
    CompensationProgressKind,
    TransitionKind,
)
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService
from tests.unit.domain.fixtures import (
    EFFECT,
    LATER,
    OP_ID,
    REQUESTER,
    RISK,
    TS,
    make_intent,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

OPERATOR = PrincipalRef(type=PrincipalType.OPERATOR, id="ops-1", display_name=None)
APPROVER = PrincipalRef(type=PrincipalType.HUMAN, id="approver-1", display_name=None)

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
def service() -> TransitionService:
    return TransitionService()


class IdSeq:
    def __init__(self, start: int = 0x10) -> None:
        self._n = start

    def next(self) -> OpaqueId:
        value = OpaqueId(value=f"00000000-0000-4000-8000-{self._n:012x}")
        self._n += 1
        return value


def make_operation(*, operation_id: OpaqueId = OP_ID) -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=operation_id,
        state=OperationState.PENDING_POLICY,
        version=1,
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


def make_policy(
    operation: Operation, *, verdict: PolicyVerdict, policy_id: OpaqueId
) -> PolicyDecision:
    return PolicyDecision(
        contract_version=CONTRACT_VERSION,
        policy_decision_id=policy_id,
        operation_id=operation.operation_id,
        operation_version=operation.version,
        intent_digest=operation.intent.intent_digest,
        verdict=verdict,
        reason_codes=(verdict.value.lower(),),
        explanation=None,
        obligations=PolicyObligations(
            require_verification=False,
            max_automatic_execution_attempts=3,
            max_automatic_recovery_attempts=3,
            automatic_compensation_allowed=False,
            operator_reason_required=False,
            approval_expires_at=None,
        ),
        policy_revision="policy-v1",
        evaluated_at=LATER,
    )


def make_pending_approval(
    operation: Operation, *, approval_id: OpaqueId, policy_id: OpaqueId
) -> Approval:
    return Approval(
        contract_version=CONTRACT_VERSION,
        approval_id=approval_id,
        operation_id=operation.operation_id,
        operation_version=next_version(operation.version),
        intent_digest=operation.intent.intent_digest,
        policy_decision_id=policy_id,
        state=ApprovalState.PENDING,
        requested_at=LATER,
        expires_at=None,
        decided_at=None,
        decided_by=None,
        reason=None,
    )


def make_evidence() -> ProviderEvidence:
    return ProviderEvidence(
        source=EvidenceSource.EXECUTION_RESPONSE,
        provider="reference",
        observed_at=LATER,
        provider_status="ok",
        provider_request_id=None,
        external_operation_id=None,
        external_resource_ids=(),
        evidence_fields=json_from_plain({"observed": "ok"}),
        raw_reference=None,
    )


def make_started_attempt(
    operation: Operation, *, attempt_id: OpaqueId, attempt_number: int
) -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=attempt_id,
        operation_id=operation.operation_id,
        attempt_number=attempt_number,
        state=AttemptState.STARTED,
        started_at=LATER,
        completed_at=None,
        provider_idempotency_key=None,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=None,
        evidence=None,
        error=None,
        correlation_id=None,
    )


def complete_attempt(
    started: ExecutionAttempt, *, outcome: EffectOutcome
) -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=started.attempt_id,
        operation_id=started.operation_id,
        attempt_number=started.attempt_number,
        state=AttemptState.COMPLETED,
        started_at=started.started_at,
        completed_at=LATER,
        provider_idempotency_key=started.provider_idempotency_key,
        external_operation_id=started.external_operation_id,
        external_resource_ids=started.external_resource_ids,
        outcome=outcome,
        evidence=make_evidence(),
        error=None,
        correlation_id=started.correlation_id,
    )


def make_verification_request(
    operation: Operation, *, verification_id: OpaqueId, attempt_id: OpaqueId | None
) -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        operation_id=operation.operation_id,
        operation_version=operation.version,
        target=VerificationTarget.ORIGINAL_EFFECT,
        target_attempt_id=attempt_id,
        effect=EFFECT,
        external_operation_id=None,
        external_resource_ids=(),
        idempotency_identity="sb:v1:verify:" + verification_id.value,
        provider_evidence_refs=(),
        requested_at=LATER,
    )


def make_verification_result(
    verification_id: OpaqueId, *, outcome: EffectOutcome
) -> VerificationResult:
    return VerificationResult(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        outcome=outcome,
        evidence=make_evidence(),
        error=None,
        completed_at=LATER,
    )


def make_compensation(
    operation: Operation, *, compensation_id: OpaqueId
) -> Compensation:
    return Compensation(
        contract_version=CONTRACT_VERSION,
        compensation_id=compensation_id,
        original_operation_id=operation.operation_id,
        kind=CompensationKind.EXACT,
        state=CompensationState.PENDING,
        version=1,
        intent_digest=operation.intent.intent_digest,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"reason": "undo"}),
        arguments_ref=None,
        idempotency_identity=compensation_idempotency_identity(compensation_id),
        requested_by=OPERATOR,
        policy_decision_id=None,
        created_at=LATER,
        updated_at=LATER,
    )


def make_compensation_attempt(
    compensation: Compensation,
    *,
    attempt_id: OpaqueId,
    attempt_number: int,
    state: AttemptState = AttemptState.STARTED,
    outcome: EffectOutcome | None = None,
) -> CompensationAttempt:
    completed = state is AttemptState.COMPLETED
    return CompensationAttempt(
        contract_version=CONTRACT_VERSION,
        compensation_attempt_id=attempt_id,
        compensation_id=compensation.compensation_id,
        attempt_number=attempt_number,
        state=state,
        started_at=LATER,
        completed_at=LATER if completed else None,
        provider_idempotency_key=None,
        external_operation_id=None,
        outcome=outcome if completed else None,
        evidence=make_evidence() if completed else None,
        error=None,
    )


def complete_compensation_attempt(
    started: CompensationAttempt, *, outcome: EffectOutcome
) -> CompensationAttempt:
    return CompensationAttempt(
        contract_version=CONTRACT_VERSION,
        compensation_attempt_id=started.compensation_attempt_id,
        compensation_id=started.compensation_id,
        attempt_number=started.attempt_number,
        state=AttemptState.COMPLETED,
        started_at=started.started_at,
        completed_at=LATER,
        provider_idempotency_key=started.provider_idempotency_key,
        external_operation_id=started.external_operation_id,
        outcome=outcome,
        evidence=make_evidence(),
        error=None,
    )


def apply_committed(
    factory: sessionmaker[Session], command: TransitionCommand
) -> TransitionResult:
    service = TransitionService()
    with unit_of_work(factory) as uow:
        return service.apply(uow, command)


@dataclass
class Scenario:
    factory: sessionmaker[Session]
    ids: IdSeq
    operation: Operation
    started_attempt: ExecutionAttempt | None = None
    verification_id: OpaqueId | None = None
    approval: Approval | None = None
    compensation: Compensation | None = None
    started_compensation_attempt: CompensationAttempt | None = None
    attempt_count: int = 0
    compensation_attempt_count: int = 0

    def apply(self, command: TransitionCommand) -> TransitionResult:
        result = apply_committed(self.factory, command)
        if result.outcome is not TransitionOutcome.APPLIED:
            raise AssertionError(f"{command.kind}: {result.reason_code}")
        assert result.operation is not None
        self.operation = result.operation
        if result.compensation is not None:
            self.compensation = result.compensation
        return result

    def _base(
        self, kind: TransitionKind, *, actor: PrincipalRef | None
    ) -> dict[str, object]:
        return {
            "kind": kind,
            "operation_id": self.operation.operation_id,
            "expected_version": self.operation.version,
            "occurred_at": LATER,
            "actor": actor,
            "correlation_id": None,
            "reason_code": kind.value.lower(),
            "transition_audit_event_id": self.ids.next(),
        }


def prefix_ready(factory: sessionmaker[Session]) -> Scenario:
    ids = IdSeq()
    created = make_operation()
    scenario = Scenario(factory=factory, ids=ids, operation=created)
    scenario.apply(
        CreateOperation(
            kind=TransitionKind.CREATE_OPERATION,
            operation=created,
            occurred_at=TS,
            actor=REQUESTER,
            correlation_id=None,
            reason_code="created",
            created_audit_event_id=ids.next(),
        )
    )
    policy_id = ids.next()
    scenario.apply(
        PolicyAllow(
            **scenario._base(TransitionKind.POLICY_ALLOW, actor=REQUESTER),  # type: ignore[arg-type]
            policy_decision=make_policy(
                scenario.operation, verdict=PolicyVerdict.ALLOW, policy_id=policy_id
            ),
            policy_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    )
    return scenario


def _create(factory: sessionmaker[Session]) -> Scenario:
    ids = IdSeq()
    created = make_operation()
    scenario = Scenario(factory=factory, ids=ids, operation=created)
    scenario.apply(
        CreateOperation(
            kind=TransitionKind.CREATE_OPERATION,
            operation=created,
            occurred_at=TS,
            actor=REQUESTER,
            correlation_id=None,
            reason_code="created",
            created_audit_event_id=ids.next(),
        )
    )
    return scenario


def _require_approval(scenario: Scenario) -> Scenario:
    policy_id = scenario.ids.next()
    approval_id = scenario.ids.next()
    pending = make_pending_approval(
        scenario.operation, approval_id=approval_id, policy_id=policy_id
    )
    scenario.apply(
        PolicyRequireApproval(
            **scenario._base(  # type: ignore[arg-type]
                TransitionKind.POLICY_REQUIRE_APPROVAL, actor=REQUESTER
            ),
            policy_decision=make_policy(
                scenario.operation,
                verdict=PolicyVerdict.REQUIRE_APPROVAL,
                policy_id=policy_id,
            ),
            approval=pending,
            policy_audit_event_id=scenario.ids.next(),
            approval_audit_event_id=scenario.ids.next(),
        )
    )
    scenario.approval = pending
    return scenario


def _claim(scenario: Scenario) -> Scenario:
    scenario.attempt_count += 1
    attempt = make_started_attempt(
        scenario.operation,
        attempt_id=scenario.ids.next(),
        attempt_number=scenario.attempt_count,
    )
    scenario.apply(
        ClaimExecution(
            **scenario._base(TransitionKind.CLAIM_EXECUTION, actor=None),  # type: ignore[arg-type]
            attempt=attempt,
            attempt_audit_event_id=scenario.ids.next(),
        )
    )
    scenario.started_attempt = attempt
    return scenario


def _execution_require(scenario: Scenario) -> Scenario:
    assert scenario.started_attempt is not None
    verification_id = scenario.ids.next()
    scenario.apply(
        ExecutionRequireVerification(
            **scenario._base(  # type: ignore[arg-type]
                TransitionKind.EXECUTION_REQUIRE_VERIFICATION, actor=None
            ),
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.APPLIED
            ),
            verification_request=make_verification_request(
                scenario.operation,
                verification_id=verification_id,
                attempt_id=scenario.started_attempt.attempt_id,
            ),
            evidence_audit_event_id=scenario.ids.next(),
            verification_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        )
    )
    scenario.verification_id = verification_id
    return scenario


def _execution_unknown(scenario: Scenario) -> Scenario:
    scenario.apply(
        ExecutionUnknown(
            **scenario._base(TransitionKind.EXECUTION_UNKNOWN, actor=None),  # type: ignore[arg-type]
            completed_attempt=None,
            evidence_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _execution_applied(scenario: Scenario) -> Scenario:
    assert scenario.started_attempt is not None
    scenario.apply(
        ExecutionApplied(
            **scenario._base(TransitionKind.EXECUTION_APPLIED, actor=None),  # type: ignore[arg-type]
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.APPLIED
            ),
            evidence_audit_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _execution_fail(scenario: Scenario) -> Scenario:
    assert scenario.started_attempt is not None
    scenario.apply(
        ExecutionNotAppliedFail(
            **scenario._base(  # type: ignore[arg-type]
                TransitionKind.EXECUTION_NOT_APPLIED_FAIL, actor=None
            ),
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.NOT_APPLIED
            ),
            evidence_audit_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _unknown_escalate(scenario: Scenario) -> Scenario:
    scenario.apply(
        UnknownEscalate(
            **scenario._base(TransitionKind.UNKNOWN_ESCALATE, actor=OPERATOR),  # type: ignore[arg-type]
            manual_audit_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _start_compensation(scenario: Scenario, kind: TransitionKind) -> Scenario:
    compensation = make_compensation(
        scenario.operation, compensation_id=scenario.ids.next()
    )
    cls = (
        SucceededStartCompensation
        if kind is TransitionKind.SUCCEEDED_START_COMPENSATION
        else FailedStartCompensation
    )
    scenario.apply(
        cls(
            **scenario._base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            compensation=compensation,
            compensation_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _claim_compensation(scenario: Scenario) -> Scenario:
    assert scenario.compensation is not None
    scenario.compensation_attempt_count += 1
    attempt = make_compensation_attempt(
        scenario.compensation,
        attempt_id=scenario.ids.next(),
        attempt_number=scenario.compensation_attempt_count,
    )
    result = apply_committed(
        scenario.factory,
        ClaimCompensationExecution(
            kind=CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION,
            operation_id=scenario.operation.operation_id,
            expected_operation_version=scenario.operation.version,
            compensation_id=scenario.compensation.compensation_id,
            expected_compensation_version=scenario.compensation.version,
            attempt=attempt,
            occurred_at=LATER,
            actor=None,
            correlation_id=None,
            reason_code="claim_compensation",
            attempt_audit_event_id=scenario.ids.next(),
        ),
    )
    if result.outcome is not TransitionOutcome.APPLIED:
        raise AssertionError(result.reason_code)
    assert result.compensation is not None
    scenario.compensation = result.compensation
    scenario.started_compensation_attempt = attempt
    return scenario


def _compensation_unknown(scenario: Scenario) -> Scenario:
    scenario.apply(
        CompensationOutcomeUnknown(
            **scenario._base(  # type: ignore[arg-type]
                TransitionKind.COMPENSATION_OUTCOME_UNKNOWN, actor=None
            ),
            completed_compensation_attempt=None,
            compensation_result_audit_event_id=scenario.ids.next(),
            outbox_event_id=scenario.ids.next(),
        )
    )
    return scenario


def _compensation_failed(scenario: Scenario) -> Scenario:
    assert scenario.started_compensation_attempt is not None
    scenario.apply(
        CompensationOutcomeFailed(
            **scenario._base(  # type: ignore[arg-type]
                TransitionKind.COMPENSATION_OUTCOME_FAILED, actor=None
            ),
            completed_compensation_attempt=complete_compensation_attempt(
                scenario.started_compensation_attempt,
                outcome=EffectOutcome.NOT_APPLIED,
            ),
            compensation_result_audit_event_id=scenario.ids.next(),
        )
    )
    return scenario


def prepare_source(factory: sessionmaker[Session], kind: TransitionKind) -> Scenario:
    source = KIND_TO_EDGE[kind][0]
    if source is None:
        ids = IdSeq()
        created = make_operation()
        return Scenario(factory=factory, ids=ids, operation=created)
    if source is OperationState.PENDING_POLICY:
        return _create(factory)
    if source is OperationState.AWAITING_APPROVAL:
        return _require_approval(_create(factory))
    if source is OperationState.READY:
        return prefix_ready(factory)
    if source is OperationState.EXECUTING:
        return _claim(prefix_ready(factory))
    if source is OperationState.VERIFYING:
        return _execution_require(_claim(prefix_ready(factory)))
    if source is OperationState.UNKNOWN:
        return _execution_unknown(_claim(prefix_ready(factory)))
    if source is OperationState.SUCCEEDED:
        return _execution_applied(_claim(prefix_ready(factory)))
    if source is OperationState.FAILED:
        return _execution_fail(_claim(prefix_ready(factory)))
    if source is OperationState.MANUAL_INTERVENTION:
        return _unknown_escalate(_execution_unknown(_claim(prefix_ready(factory))))
    if source is OperationState.COMPENSATING:
        return _claim_compensation(
            _start_compensation(
                _execution_applied(_claim(prefix_ready(factory))),
                TransitionKind.SUCCEEDED_START_COMPENSATION,
            )
        )
    if source is OperationState.COMPENSATION_UNKNOWN:
        return _compensation_unknown(
            _claim_compensation(
                _start_compensation(
                    _execution_applied(_claim(prefix_ready(factory))),
                    TransitionKind.SUCCEEDED_START_COMPENSATION,
                )
            )
        )
    if source is OperationState.COMPENSATION_FAILED:
        return _compensation_failed(
            _claim_compensation(
                _start_compensation(
                    _execution_applied(_claim(prefix_ready(factory))),
                    TransitionKind.SUCCEEDED_START_COMPENSATION,
                )
            )
        )
    raise AssertionError(f"unhandled source {source}")


def command_for(scenario: Scenario, kind: TransitionKind) -> TransitionCommand:
    ids = scenario.ids
    base = scenario._base
    operation = scenario.operation
    if kind is TransitionKind.CREATE_OPERATION:
        return CreateOperation(
            kind=kind,
            operation=operation,
            occurred_at=TS,
            actor=REQUESTER,
            correlation_id=None,
            reason_code="created",
            created_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.POLICY_ALLOW:
        return PolicyAllow(
            **base(kind, actor=REQUESTER),  # type: ignore[arg-type]
            policy_decision=make_policy(
                operation, verdict=PolicyVerdict.ALLOW, policy_id=ids.next()
            ),
            policy_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.POLICY_REQUIRE_APPROVAL:
        policy_id = ids.next()
        return PolicyRequireApproval(
            **base(kind, actor=REQUESTER),  # type: ignore[arg-type]
            policy_decision=make_policy(
                operation, verdict=PolicyVerdict.REQUIRE_APPROVAL, policy_id=policy_id
            ),
            approval=make_pending_approval(
                operation, approval_id=ids.next(), policy_id=policy_id
            ),
            policy_audit_event_id=ids.next(),
            approval_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.POLICY_DENY:
        return PolicyDeny(
            **base(kind, actor=REQUESTER),  # type: ignore[arg-type]
            policy_decision=make_policy(
                operation, verdict=PolicyVerdict.DENY, policy_id=ids.next()
            ),
            policy_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.CANCEL_PENDING_POLICY:
        return CancelPendingPolicy(**base(kind, actor=OPERATOR))  # type: ignore[arg-type]
    if kind is TransitionKind.APPROVAL_GRANT:
        assert scenario.approval is not None
        granted = Approval(
            contract_version=CONTRACT_VERSION,
            approval_id=scenario.approval.approval_id,
            operation_id=operation.operation_id,
            operation_version=operation.version,
            intent_digest=operation.intent.intent_digest,
            policy_decision_id=scenario.approval.policy_decision_id,
            state=ApprovalState.APPROVED,
            requested_at=scenario.approval.requested_at,
            expires_at=None,
            decided_at=LATER,
            decided_by=APPROVER,
            reason="approved",
        )
        return ApprovalGrant(
            **base(kind, actor=APPROVER),  # type: ignore[arg-type]
            approval=granted,
            approval_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.APPROVAL_REJECT:
        assert scenario.approval is not None
        rejected = Approval(
            contract_version=CONTRACT_VERSION,
            approval_id=scenario.approval.approval_id,
            operation_id=operation.operation_id,
            operation_version=operation.version,
            intent_digest=operation.intent.intent_digest,
            policy_decision_id=scenario.approval.policy_decision_id,
            state=ApprovalState.REJECTED,
            requested_at=scenario.approval.requested_at,
            expires_at=None,
            decided_at=LATER,
            decided_by=APPROVER,
            reason="rejected",
        )
        return ApprovalReject(
            **base(kind, actor=APPROVER),  # type: ignore[arg-type]
            approval=rejected,
            approval_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.CANCEL_AWAITING_APPROVAL:
        assert scenario.approval is not None
        cancelled = Approval(
            contract_version=CONTRACT_VERSION,
            approval_id=scenario.approval.approval_id,
            operation_id=operation.operation_id,
            operation_version=operation.version,
            intent_digest=operation.intent.intent_digest,
            policy_decision_id=scenario.approval.policy_decision_id,
            state=ApprovalState.CANCELLED,
            requested_at=scenario.approval.requested_at,
            expires_at=None,
            decided_at=LATER,
            decided_by=OPERATOR,
            reason="cancelled",
        )
        return CancelAwaitingApproval(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            approval=cancelled,
        )
    if kind is TransitionKind.CLAIM_EXECUTION:
        scenario.attempt_count += 1
        attempt = make_started_attempt(
            operation, attempt_id=ids.next(), attempt_number=scenario.attempt_count
        )
        scenario.started_attempt = attempt
        return ClaimExecution(
            **base(kind, actor=None),  # type: ignore[arg-type]
            attempt=attempt,
            attempt_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.CANCEL_READY:
        return CancelReady(**base(kind, actor=OPERATOR))  # type: ignore[arg-type]
    if kind is TransitionKind.READY_MESSAGING_RECOVERY_EXHAUSTED:
        return ReadyMessagingRecoveryExhausted(
            **base(kind, actor=None),  # type: ignore[arg-type]
        )
    if kind is TransitionKind.EXECUTION_APPLIED:
        assert scenario.started_attempt is not None
        return ExecutionApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.APPLIED
            ),
            evidence_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.EXECUTION_REQUIRE_VERIFICATION:
        assert scenario.started_attempt is not None
        verification_id = ids.next()
        scenario.verification_id = verification_id
        return ExecutionRequireVerification(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.APPLIED
            ),
            verification_request=make_verification_request(
                operation,
                verification_id=verification_id,
                attempt_id=scenario.started_attempt.attempt_id,
            ),
            evidence_audit_event_id=ids.next(),
            verification_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.EXECUTION_NOT_APPLIED_RETRY:
        assert scenario.started_attempt is not None
        return ExecutionNotAppliedRetry(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.NOT_APPLIED
            ),
            idempotency_mode=IdempotencyMode.NONE,
            evidence_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.EXECUTION_NOT_APPLIED_FAIL:
        assert scenario.started_attempt is not None
        return ExecutionNotAppliedFail(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_attempt=complete_attempt(
                scenario.started_attempt, outcome=EffectOutcome.NOT_APPLIED
            ),
            evidence_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.EXECUTION_UNKNOWN:
        return ExecutionUnknown(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_attempt=None,
            evidence_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.EXECUTION_MESSAGING_RECOVERY_EXHAUSTED:
        return ExecutionMessagingRecoveryExhausted(
            **base(kind, actor=None),  # type: ignore[arg-type]
        )
    if kind is TransitionKind.VERIFICATION_APPLIED:
        assert scenario.verification_id is not None
        return VerificationApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            verification_result=make_verification_result(
                scenario.verification_id, outcome=EffectOutcome.APPLIED
            ),
            verification_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.VERIFICATION_NOT_APPLIED_RETRY:
        assert scenario.verification_id is not None
        return VerificationNotAppliedRetry(
            **base(kind, actor=None),  # type: ignore[arg-type]
            verification_result=make_verification_result(
                scenario.verification_id, outcome=EffectOutcome.NOT_APPLIED
            ),
            idempotency_mode=IdempotencyMode.NONE,
            verification_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.VERIFICATION_NOT_APPLIED_FAIL:
        assert scenario.verification_id is not None
        return VerificationNotAppliedFail(
            **base(kind, actor=None),  # type: ignore[arg-type]
            verification_result=make_verification_result(
                scenario.verification_id, outcome=EffectOutcome.NOT_APPLIED
            ),
            verification_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.VERIFICATION_INCONCLUSIVE:
        assert scenario.verification_id is not None
        return VerificationInconclusive(
            **base(kind, actor=None),  # type: ignore[arg-type]
            verification_result=make_verification_result(
                scenario.verification_id, outcome=EffectOutcome.UNKNOWN
            ),
            verification_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.VERIFICATION_ESCALATE:
        return VerificationEscalate(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            verification_result=None,
            manual_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.UNKNOWN_START_VERIFICATION:
        verification_id = ids.next()
        scenario.verification_id = verification_id
        attempt_id = (
            None
            if scenario.started_attempt is None
            else scenario.started_attempt.attempt_id
        )
        return UnknownStartVerification(
            **base(kind, actor=None),  # type: ignore[arg-type]
            verification_request=make_verification_request(
                operation, verification_id=verification_id, attempt_id=attempt_id
            ),
            verification_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.UNKNOWN_SAFE_RETRY:
        return UnknownSafeRetry(
            **base(kind, actor=None),  # type: ignore[arg-type]
            idempotency_mode=IdempotencyMode.NONE,
            execution_outcome=EffectOutcome.NOT_APPLIED,
            verification_outcome=None,
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.UNKNOWN_RECONCILE_APPLIED:
        return UnknownReconcileApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            reconciliation=StoredReconciliationDecision(
                reconciliation_decision_id=ids.next(),
                operation_id=operation.operation_id,
                operation_version=operation.version,
                verification_id=None,
                decision=ReconciliationDecision(
                    action=ReconciliationAction.MARK_SUCCEEDED,
                    reason_code="operator_mark_succeeded",
                ),
                created_at=LATER,
            ),
            reconciliation_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.UNKNOWN_RECONCILE_NOT_APPLIED:
        return UnknownReconcileNotApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            reconciliation=StoredReconciliationDecision(
                reconciliation_decision_id=ids.next(),
                operation_id=operation.operation_id,
                operation_version=operation.version,
                verification_id=None,
                decision=ReconciliationDecision(
                    action=ReconciliationAction.MARK_FAILED,
                    reason_code="operator_mark_failed",
                ),
                created_at=LATER,
            ),
            reconciliation_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.UNKNOWN_ESCALATE:
        return UnknownEscalate(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            manual_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.SUCCEEDED_START_COMPENSATION:
        compensation = make_compensation(operation, compensation_id=ids.next())
        scenario.compensation = compensation
        return SucceededStartCompensation(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            compensation=compensation,
            compensation_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.FAILED_START_COMPENSATION:
        compensation = make_compensation(operation, compensation_id=ids.next())
        scenario.compensation = compensation
        return FailedStartCompensation(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            compensation=compensation,
            compensation_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.MANUAL_START_VERIFICATION:
        verification_id = ids.next()
        scenario.verification_id = verification_id
        attempt_id = (
            None
            if scenario.started_attempt is None
            else scenario.started_attempt.attempt_id
        )
        return ManualStartVerification(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            verification_request=make_verification_request(
                operation, verification_id=verification_id, attempt_id=attempt_id
            ),
            operator_audit_event_id=ids.next(),
            verification_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.MANUAL_START_COMPENSATION:
        compensation = make_compensation(operation, compensation_id=ids.next())
        scenario.compensation = compensation
        return ManualStartCompensation(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            compensation=compensation,
            operator_audit_event_id=ids.next(),
            compensation_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.MANUAL_SAFE_RETRY:
        return ManualSafeRetry(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            idempotency_mode=IdempotencyMode.NONE,
            execution_outcome=EffectOutcome.NOT_APPLIED,
            verification_outcome=None,
            operator_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_APPLIED:
        assert scenario.started_compensation_attempt is not None
        return CompensationApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_compensation_attempt=complete_compensation_attempt(
                scenario.started_compensation_attempt, outcome=EffectOutcome.APPLIED
            ),
            compensation_result_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_UNKNOWN:
        return CompensationOutcomeUnknown(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_compensation_attempt=None,
            compensation_result_audit_event_id=ids.next(),
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_FAILED:
        assert scenario.started_compensation_attempt is not None
        return CompensationOutcomeFailed(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_compensation_attempt=complete_compensation_attempt(
                scenario.started_compensation_attempt,
                outcome=EffectOutcome.NOT_APPLIED,
            ),
            compensation_result_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_ESCALATE:
        return CompensationEscalate(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            manual_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_UNKNOWN_RETRY:
        return CompensationUnknownRetry(
            **base(kind, actor=None),  # type: ignore[arg-type]
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_UNKNOWN_APPLIED:
        assert scenario.started_compensation_attempt is not None
        return CompensationUnknownApplied(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_compensation_attempt=complete_compensation_attempt(
                scenario.started_compensation_attempt, outcome=EffectOutcome.APPLIED
            ),
        )
    if kind is TransitionKind.COMPENSATION_UNKNOWN_FAILED:
        assert scenario.started_compensation_attempt is not None
        return CompensationUnknownFailed(
            **base(kind, actor=None),  # type: ignore[arg-type]
            completed_compensation_attempt=complete_compensation_attempt(
                scenario.started_compensation_attempt,
                outcome=EffectOutcome.NOT_APPLIED,
            ),
        )
    if kind is TransitionKind.COMPENSATION_UNKNOWN_ESCALATE:
        return CompensationUnknownEscalate(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            manual_audit_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_FAILED_RETRY:
        return CompensationFailedRetry(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            outbox_event_id=ids.next(),
        )
    if kind is TransitionKind.COMPENSATION_FAILED_ESCALATE:
        return CompensationFailedEscalate(
            **base(kind, actor=OPERATOR),  # type: ignore[arg-type]
            manual_audit_event_id=ids.next(),
        )
    raise AssertionError(f"unhandled kind {kind}")
