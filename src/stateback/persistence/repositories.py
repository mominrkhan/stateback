from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    ApprovalState,
    AttemptState,
    ErrorKind,
    OperationState,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval, PolicyDecision
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.exceptions import (
    AppendOnlyViolationError,
    ConcurrencyConflictError,
    DuplicateKeyError,
    NotFoundError,
    PersistenceError,
)
from stateback.persistence.mapping import (
    approval_from_row,
    approval_to_row,
    attempt_from_row,
    attempt_to_row,
    audit_from_row,
    audit_to_row,
    compensation_attempt_from_row,
    compensation_attempt_to_row,
    compensation_from_row,
    compensation_to_row,
    operation_from_row,
    operation_to_row,
    outbox_from_row,
    outbox_to_row,
    policy_from_row,
    policy_to_row,
    reconciliation_from_row,
    reconciliation_to_row,
    verification_from_row,
    verification_to_row,
)
from stateback.persistence.models import (
    ApprovalRow,
    AuditEventRow,
    CompensationAttemptRow,
    CompensationRow,
    ExecutionAttemptRow,
    OperationRow,
    OutboxEventRow,
    PolicyDecisionRow,
    ReconciliationDecisionRow,
    VerificationRow,
)
from stateback.persistence.types import (
    StoredReconciliationDecision,
    opaque_to_uuid,
)

_DUPLICATE_CONSTRAINTS: dict[str, str] = {
    "pk_operations": "duplicate_operation_id",
    "uq_operations_idempotency_identity": "duplicate_idempotency_identity",
    "pk_execution_attempts": "duplicate_attempt_id",
    "uq_execution_attempts_operation_id_attempt_number": "duplicate_attempt_number",
    "pk_policy_decisions": "duplicate_policy_decision_id",
    "pk_approvals": "duplicate_approval_id",
    "pk_verifications": "duplicate_verification_id",
    "pk_compensations": "duplicate_compensation_id",
    "uq_compensations_idempotency_identity": "duplicate_compensation_idempotency",
    "pk_compensation_attempts": "duplicate_compensation_attempt_id",
    "uq_compensation_attempts_compensation_id_attempt_number": (
        "duplicate_compensation_attempt_number"
    ),
    "pk_audit_events": "duplicate_audit_event_id",
    "uq_audit_events_operation_id_sequence": "duplicate_audit_sequence",
    "pk_outbox_events": "duplicate_outbox_event_id",
    "pk_reconciliation_decisions": "duplicate_reconciliation_decision_id",
}

_SAFE_DUPLICATE_MESSAGES: dict[str, str] = {
    "duplicate_operation_id": "duplicate operation_id",
    "duplicate_idempotency_identity": "duplicate idempotency_identity",
    "duplicate_attempt_id": "duplicate attempt_id",
    "duplicate_attempt_number": "duplicate attempt_number",
    "duplicate_policy_decision_id": "duplicate policy_decision_id",
    "duplicate_approval_id": "duplicate approval_id",
    "duplicate_verification_id": "duplicate verification_id",
    "duplicate_compensation_id": "duplicate compensation_id",
    "duplicate_compensation_idempotency": "duplicate compensation idempotency_identity",
    "duplicate_compensation_attempt_id": "duplicate compensation_attempt_id",
    "duplicate_compensation_attempt_number": "duplicate compensation attempt_number",
    "duplicate_audit_event_id": "duplicate audit_event_id",
    "duplicate_audit_sequence": "duplicate audit sequence",
    "duplicate_outbox_event_id": "duplicate outbox event_id",
    "duplicate_reconciliation_decision_id": "duplicate reconciliation_decision_id",
}


def _constraint_name(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    diag = getattr(orig, "diag", None)
    if diag is not None:
        name = getattr(diag, "constraint_name", None)
        if name:
            return str(name)
    text = str(orig)
    for name in _DUPLICATE_CONSTRAINTS:
        if name in text:
            return name
    return None


def _sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", exc)
    state = getattr(orig, "sqlstate", None)
    if state is None:
        return None
    return str(state)


def _is_append_only(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", exc)
    text = str(orig).lower()
    if "append-only" in text:
        return True
    return _sqlstate(exc) == "23001"


def map_db_error(exc: BaseException) -> PersistenceError | None:
    if _is_append_only(exc):
        return AppendOnlyViolationError(
            "append-only table cannot be updated or deleted"
        )
    sqlstate = _sqlstate(exc)
    constraint = _constraint_name(exc)
    if sqlstate == "23505" or constraint in _DUPLICATE_CONSTRAINTS:
        reason = _DUPLICATE_CONSTRAINTS.get(constraint or "", "")
        if not reason:
            lowered = str(getattr(exc, "orig", exc)).lower()
            for name, mapped in _DUPLICATE_CONSTRAINTS.items():
                if name.lower() in lowered:
                    reason = mapped
                    break
        if reason:
            return DuplicateKeyError(reason, _SAFE_DUPLICATE_MESSAGES[reason])
    if sqlstate == "23503" or (constraint is not None and constraint.startswith("fk_")):
        return PersistenceError(
            "fk_violation",
            "foreign key constraint violated",
            error_kind=ErrorKind.PERSISTENCE,
        )
    if sqlstate == "23514" or (constraint is not None and constraint.startswith("ck_")):
        return PersistenceError(
            "check_violation",
            "check constraint violated",
            error_kind=ErrorKind.PERSISTENCE,
        )
    return None


def _rowcount(result: object) -> int:
    count = getattr(result, "rowcount", None)
    if not isinstance(count, int):
        return -1
    return count


def _reraise_db(exc: BaseException) -> None:
    mapped = map_db_error(exc)
    if mapped is not None:
        raise mapped from exc
    raise exc


class _SessionOps:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _flush(self) -> None:
        try:
            self.session.flush()
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)


class OperationRepository(_SessionOps):
    def insert(self, operation: Operation) -> None:
        if operation.version != 1:
            raise PersistenceError(
                "check_violation",
                "insert requires operation.version == 1",
                error_kind=ErrorKind.PERSISTENCE,
            )
        self.session.add(operation_to_row(operation))
        self._flush()

    def get(self, operation_id: OpaqueId) -> Operation | None:
        row = self.session.get(OperationRow, opaque_to_uuid(operation_id))
        if row is None:
            return None
        return operation_from_row(row)

    def get_for_update(self, operation_id: OpaqueId) -> Operation | None:
        stmt = (
            select(OperationRow)
            .where(OperationRow.operation_id == opaque_to_uuid(operation_id))
            .with_for_update()
        )
        row = self.session.scalars(stmt).one_or_none()
        if row is None:
            return None
        return operation_from_row(row)

    def get_by_idempotency_identity(self, identity: str) -> Operation | None:
        stmt = select(OperationRow).where(OperationRow.idempotency_identity == identity)
        row = self.session.scalars(stmt).one_or_none()
        if row is None:
            return None
        return operation_from_row(row)

    def list_by_state(self, state: OperationState) -> list[Operation]:
        stmt = (
            select(OperationRow)
            .where(OperationRow.state == state.value)
            .order_by(OperationRow.created_at, OperationRow.operation_id)
        )
        return [operation_from_row(row) for row in self.session.scalars(stmt)]

    def update_cas(self, expected_version: int, operation: Operation) -> None:
        if operation.version != expected_version + 1:
            raise ConcurrencyConflictError("CAS version must be expected_version + 1")
        row = operation_to_row(operation)
        stmt = (
            update(OperationRow)
            .where(
                OperationRow.operation_id == row.operation_id,
                OperationRow.version == expected_version,
            )
            .values(
                contract_version=row.contract_version,
                state=row.state,
                version=row.version,
                intent=row.intent,
                intent_digest=row.intent_digest,
                risk_level=row.risk_level,
                idempotency_identity=row.idempotency_identity,
                current_policy_decision_id=row.current_policy_decision_id,
                current_approval_id=row.current_approval_id,
                latest_attempt_id=row.latest_attempt_id,
                latest_verification_id=row.latest_verification_id,
                compensation_id=row.compensation_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise ConcurrencyConflictError("operation version conflict")


class AttemptRepository(_SessionOps):
    def insert(self, attempt: ExecutionAttempt) -> None:
        self.session.add(attempt_to_row(attempt))
        self._flush()

    def get(self, attempt_id: OpaqueId) -> ExecutionAttempt | None:
        row = self.session.get(ExecutionAttemptRow, opaque_to_uuid(attempt_id))
        if row is None:
            return None
        return attempt_from_row(row)

    def list_for_operation(self, operation_id: OpaqueId) -> list[ExecutionAttempt]:
        stmt = (
            select(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.operation_id == opaque_to_uuid(operation_id))
            .order_by(ExecutionAttemptRow.attempt_number)
        )
        return [attempt_from_row(row) for row in self.session.scalars(stmt)]

    def complete(self, attempt: ExecutionAttempt) -> None:
        if attempt.state is not AttemptState.COMPLETED:
            raise PersistenceError(
                "attempt_not_started",
                "complete requires a COMPLETED attempt",
                error_kind=ErrorKind.PERSISTENCE,
            )
        row = attempt_to_row(attempt)
        stmt = (
            update(ExecutionAttemptRow)
            .where(
                ExecutionAttemptRow.attempt_id == row.attempt_id,
                ExecutionAttemptRow.state == AttemptState.STARTED.value,
            )
            .values(
                state=row.state,
                completed_at=row.completed_at,
                provider_idempotency_key=row.provider_idempotency_key,
                external_operation_id=row.external_operation_id,
                external_resource_ids=row.external_resource_ids,
                outcome=row.outcome,
                evidence=row.evidence,
                error=row.error,
                correlation_id=row.correlation_id,
            )
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise PersistenceError(
                "attempt_not_started",
                "attempt is missing or not STARTED",
                error_kind=ErrorKind.PERSISTENCE,
            )


class PolicyDecisionRepository(_SessionOps):
    def insert(self, decision: PolicyDecision) -> None:
        self.session.add(policy_to_row(decision))
        self._flush()

    def get(self, policy_decision_id: OpaqueId) -> PolicyDecision | None:
        row = self.session.get(PolicyDecisionRow, opaque_to_uuid(policy_decision_id))
        if row is None:
            return None
        return policy_from_row(row)

    def list_for_operation(self, operation_id: OpaqueId) -> list[PolicyDecision]:
        stmt = (
            select(PolicyDecisionRow)
            .where(PolicyDecisionRow.operation_id == opaque_to_uuid(operation_id))
            .order_by(
                PolicyDecisionRow.evaluated_at, PolicyDecisionRow.policy_decision_id
            )
        )
        return [policy_from_row(row) for row in self.session.scalars(stmt)]


class ApprovalRepository(_SessionOps):
    def insert(self, approval: Approval) -> None:
        self.session.add(approval_to_row(approval))
        self._flush()

    def get(self, approval_id: OpaqueId) -> Approval | None:
        row = self.session.get(ApprovalRow, opaque_to_uuid(approval_id))
        if row is None:
            return None
        return approval_from_row(row)

    def list_for_operation(self, operation_id: OpaqueId) -> list[Approval]:
        stmt = (
            select(ApprovalRow)
            .where(ApprovalRow.operation_id == opaque_to_uuid(operation_id))
            .order_by(ApprovalRow.requested_at, ApprovalRow.approval_id)
        )
        return [approval_from_row(row) for row in self.session.scalars(stmt)]

    def update_cas_state(
        self, approval: Approval, expected_state: ApprovalState
    ) -> None:
        row = approval_to_row(approval)
        stmt = (
            update(ApprovalRow)
            .where(
                ApprovalRow.approval_id == row.approval_id,
                ApprovalRow.state == expected_state.value,
            )
            .values(
                contract_version=row.contract_version,
                operation_id=row.operation_id,
                operation_version=row.operation_version,
                intent_digest=row.intent_digest,
                policy_decision_id=row.policy_decision_id,
                state=row.state,
                requested_at=row.requested_at,
                expires_at=row.expires_at,
                decided_at=row.decided_at,
                decided_by=row.decided_by,
                reason=row.reason,
            )
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise ConcurrencyConflictError("approval state conflict")


class VerificationRepository(_SessionOps):
    def insert_request(self, request: VerificationRequest) -> None:
        self.session.add(verification_to_row(request, None))
        self._flush()

    def get(
        self, verification_id: OpaqueId
    ) -> tuple[VerificationRequest, VerificationResult | None] | None:
        row = self.session.get(VerificationRow, opaque_to_uuid(verification_id))
        if row is None:
            return None
        return verification_from_row(row)

    def list_for_operation(
        self, operation_id: OpaqueId
    ) -> list[tuple[VerificationRequest, VerificationResult | None]]:
        stmt = (
            select(VerificationRow)
            .where(VerificationRow.operation_id == opaque_to_uuid(operation_id))
            .order_by(VerificationRow.requested_at, VerificationRow.verification_id)
        )
        return [verification_from_row(row) for row in self.session.scalars(stmt)]

    def complete(self, result: VerificationResult) -> None:
        stmt = (
            update(VerificationRow)
            .where(
                VerificationRow.verification_id
                == opaque_to_uuid(result.verification_id),
                VerificationRow.result_completed_at.is_(None),
            )
            .values(
                result_outcome=result.outcome.value,
                result_evidence=result.evidence.to_wire(),
                result_error=None if result.error is None else result.error.to_wire(),
                result_completed_at=result.completed_at.value,
            )
        )
        try:
            executed = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(executed) == 1:
            return
        existing = self.session.get(
            VerificationRow, opaque_to_uuid(result.verification_id)
        )
        if existing is None:
            raise PersistenceError(
                "not_found",
                "verification request not found",
                error_kind=ErrorKind.PERSISTENCE,
            )
        raise PersistenceError(
            "check_violation",
            "verification result already present",
            error_kind=ErrorKind.PERSISTENCE,
        )


class CompensationRepository(_SessionOps):
    def insert(self, compensation: Compensation) -> None:
        self.session.add(compensation_to_row(compensation))
        self._flush()

    def get(self, compensation_id: OpaqueId) -> Compensation | None:
        row = self.session.get(CompensationRow, opaque_to_uuid(compensation_id))
        if row is None:
            return None
        return compensation_from_row(row)

    def get_by_original_operation(self, operation_id: OpaqueId) -> Compensation | None:
        stmt = select(CompensationRow).where(
            CompensationRow.original_operation_id == opaque_to_uuid(operation_id)
        )
        row = self.session.scalars(stmt).one_or_none()
        if row is None:
            return None
        return compensation_from_row(row)

    def update_cas(self, expected_version: int, compensation: Compensation) -> None:
        if compensation.version != expected_version + 1:
            raise ConcurrencyConflictError("CAS version must be expected_version + 1")
        row = compensation_to_row(compensation)
        stmt = (
            update(CompensationRow)
            .where(
                CompensationRow.compensation_id == row.compensation_id,
                CompensationRow.version == expected_version,
            )
            .values(
                contract_version=row.contract_version,
                original_operation_id=row.original_operation_id,
                kind=row.kind,
                state=row.state,
                version=row.version,
                intent_digest=row.intent_digest,
                arguments_mode=row.arguments_mode,
                arguments=row.arguments,
                arguments_ref=row.arguments_ref,
                idempotency_identity=row.idempotency_identity,
                requested_by=row.requested_by,
                policy_decision_id=row.policy_decision_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise ConcurrencyConflictError("compensation version conflict")


class CompensationAttemptRepository(_SessionOps):
    def insert(self, attempt: CompensationAttempt) -> None:
        self.session.add(compensation_attempt_to_row(attempt))
        self._flush()

    def get(self, compensation_attempt_id: OpaqueId) -> CompensationAttempt | None:
        row = self.session.get(
            CompensationAttemptRow, opaque_to_uuid(compensation_attempt_id)
        )
        if row is None:
            return None
        return compensation_attempt_from_row(row)

    def list_for_compensation(
        self, compensation_id: OpaqueId
    ) -> list[CompensationAttempt]:
        stmt = (
            select(CompensationAttemptRow)
            .where(
                CompensationAttemptRow.compensation_id
                == opaque_to_uuid(compensation_id)
            )
            .order_by(CompensationAttemptRow.attempt_number)
        )
        return [
            compensation_attempt_from_row(row) for row in self.session.scalars(stmt)
        ]

    def complete(self, attempt: CompensationAttempt) -> None:
        if attempt.state is not AttemptState.COMPLETED:
            raise PersistenceError(
                "attempt_not_started",
                "complete requires a COMPLETED compensation attempt",
                error_kind=ErrorKind.PERSISTENCE,
            )
        row = compensation_attempt_to_row(attempt)
        stmt = (
            update(CompensationAttemptRow)
            .where(
                CompensationAttemptRow.compensation_attempt_id
                == row.compensation_attempt_id,
                CompensationAttemptRow.state == AttemptState.STARTED.value,
            )
            .values(
                state=row.state,
                completed_at=row.completed_at,
                provider_idempotency_key=row.provider_idempotency_key,
                external_operation_id=row.external_operation_id,
                outcome=row.outcome,
                evidence=row.evidence,
                error=row.error,
            )
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise PersistenceError(
                "attempt_not_started",
                "compensation attempt is missing or not STARTED",
                error_kind=ErrorKind.PERSISTENCE,
            )


class AuditRepository(_SessionOps):
    def append(self, event: AuditEvent) -> None:
        self.session.add(audit_to_row(event))
        try:
            self.session.flush()
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)

    def list_for_operation(self, operation_id: OpaqueId) -> list[AuditEvent]:
        stmt = (
            select(AuditEventRow)
            .where(AuditEventRow.operation_id == opaque_to_uuid(operation_id))
            .order_by(AuditEventRow.sequence)
        )
        return [audit_from_row(row) for row in self.session.scalars(stmt)]

    def next_sequence(self, operation_id: OpaqueId) -> int:
        """Return MAX(sequence)+1, or 1 if none.

        Safe only if the caller already holds get_for_update on that operation
        in the same unit of work. This method does not take the lock.
        """
        stmt = select(func.max(AuditEventRow.sequence)).where(
            AuditEventRow.operation_id == opaque_to_uuid(operation_id)
        )
        maximum = self.session.scalar(stmt)
        if maximum is None:
            return 1
        return int(maximum) + 1


class OutboxRepository(_SessionOps):
    def insert(self, event: OutboxEvent) -> None:
        self.session.add(outbox_to_row(event))
        self._flush()

    def get(self, event_id: OpaqueId) -> OutboxEvent | None:
        row = self.session.get(OutboxEventRow, opaque_to_uuid(event_id))
        if row is None:
            return None
        return outbox_from_row(row)

    def list_pending_for_claim(self, limit: int) -> list[OutboxEvent]:
        if limit < 1:
            raise PersistenceError(
                "check_violation",
                "limit must be >= 1",
                error_kind=ErrorKind.PERSISTENCE,
            )
        stmt = (
            select(OutboxEventRow)
            .where(OutboxEventRow.state == "PENDING")
            .order_by(OutboxEventRow.created_at, OutboxEventRow.event_id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [outbox_from_row(row) for row in self.session.scalars(stmt)]

    def mark_published(self, event_id: OpaqueId, published_at: UtcTimestamp) -> None:
        row = self.session.get(OutboxEventRow, opaque_to_uuid(event_id))
        if row is None:
            raise NotFoundError("outbox event not found")
        if row.state == "PUBLISHED":
            return
        stmt = (
            update(OutboxEventRow)
            .where(
                OutboxEventRow.event_id == opaque_to_uuid(event_id),
                OutboxEventRow.state == "PENDING",
            )
            .values(state="PUBLISHED", published_at=published_at.value)
        )
        try:
            result = self.session.execute(stmt)
        except (IntegrityError, DBAPIError) as exc:
            _reraise_db(exc)
        if _rowcount(result) != 1:
            raise PersistenceError(
                "outbox_not_pending",
                "outbox event is not PENDING",
                error_kind=ErrorKind.PERSISTENCE,
            )


class ReconciliationRepository(_SessionOps):
    def insert(self, stored: StoredReconciliationDecision) -> None:
        self.session.add(reconciliation_to_row(stored))
        self._flush()

    def list_for_operation(
        self, operation_id: OpaqueId
    ) -> list[StoredReconciliationDecision]:
        stmt = (
            select(ReconciliationDecisionRow)
            .where(
                ReconciliationDecisionRow.operation_id == opaque_to_uuid(operation_id)
            )
            .order_by(
                ReconciliationDecisionRow.created_at,
                ReconciliationDecisionRow.reconciliation_decision_id,
            )
        )
        return [reconciliation_from_row(row) for row in self.session.scalars(stmt)]
