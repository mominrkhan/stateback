"""Authoritative lifecycle-mutation path."""

from __future__ import annotations

from stateback.domain.audit import AuditEvent
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.crash import interpret_execution_crash
from stateback.domain.enums import (
    ABSOLUTE_TERMINAL_STATES,
    INITIAL_AUDIT_SEQUENCE,
    INITIAL_OPERATION_VERSION,
    ApprovalState,
    AttemptState,
    AuditEventType,
    CompensationState,
    OperationState,
    TransitionVerdict,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue, json_from_plain
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation, next_version
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.transitions import evaluate_operation_transition
from stateback.persistence.exceptions import ConcurrencyConflictError, NotFoundError
from stateback.persistence.uow import UnitOfWork
from stateback.transitions.audit import ALLOWED_AUDIT_DATA_KEYS, build_audit_event
from stateback.transitions.commands import (
    COMMAND_TYPE_TO_KIND,
    ApprovalGrant,
    ApprovalReject,
    CancelAwaitingApproval,
    ClaimCompensationExecution,
    ClaimCompensationRetryAttempt,
    ClaimExecution,
    CompensationApplied,
    CompensationEscalate,
    CompensationOutcomeFailed,
    CompensationOutcomeUnknown,
    CompensationUnknownApplied,
    CompensationUnknownEscalate,
    CompensationUnknownFailed,
    CreateOperation,
    ExecutionApplied,
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
    RetryCompensationAfterVerification,
    StartCompensationVerification,
    SucceededStartCompensation,
    TransitionCommand,
    UnknownReconcileApplied,
    UnknownReconcileNotApplied,
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
from stateback.transitions.mutate import replace_compensation, replace_operation
from stateback.transitions.outbox import OUTBOX_COMMAND_FOR_KIND, build_outbox_event
from stateback.transitions.preconditions import (
    COMPENSATION_TARGET_STATE,
    ESCALATE_KINDS,
    RelatedRecords,
    evaluate_claim_compensation_preconditions,
    evaluate_claim_compensation_retry_attempt_preconditions,
    evaluate_preconditions,
    evaluate_retry_compensation_after_verification_preconditions,
    evaluate_start_compensation_verification_preconditions,
)
from stateback.transitions.results import TransitionOutcome, TransitionResult


def _audit_data(**pairs: object) -> JsonValue:
    payload: dict[str, object] = {}
    for key, value in pairs.items():
        if value is None or key not in ALLOWED_AUDIT_DATA_KEYS:
            continue
        payload[key] = value.value if hasattr(value, "value") else value
    return json_from_plain(payload)


class TransitionService:
    def apply(self, uow: UnitOfWork, command: TransitionCommand) -> TransitionResult:
        expected = COMMAND_TYPE_TO_KIND.get(type(command))
        if expected is None or command.kind is not expected:
            raise ValueError("command kind does not match command type")
        if isinstance(command, CreateOperation):
            return self._apply_create(uow, command)
        if isinstance(command, ClaimCompensationExecution):
            return self._apply_claim_compensation(uow, command)
        if isinstance(command, StartCompensationVerification):
            return self._apply_start_compensation_verification(uow, command)
        if isinstance(command, ClaimCompensationRetryAttempt):
            return self._apply_claim_compensation_retry_attempt(uow, command)
        if isinstance(command, RetryCompensationAfterVerification):
            return self._apply_retry_compensation_after_verification(uow, command)
        return self._apply_operation(uow, command)

    def _apply_create(
        self, uow: UnitOfWork, command: CreateOperation
    ) -> TransitionResult:
        operation = command.operation
        if operation.state is not OperationState.PENDING_POLICY:
            return self._rejected(
                command.kind,
                "create_requires_pending_policy",
                None,
                None,
                OperationState.PENDING_POLICY,
                None,
            )
        if operation.version != INITIAL_OPERATION_VERSION:
            return self._rejected(
                command.kind,
                "create_requires_version_1",
                None,
                None,
                OperationState.PENDING_POLICY,
                operation.version,
            )
        if (
            operation.created_at != command.occurred_at
            or operation.updated_at != command.occurred_at
        ):
            raise ValueError("create timestamps must equal occurred_at")
        listed = evaluate_operation_transition(None, OperationState.PENDING_POLICY)
        if listed.verdict is not TransitionVerdict.LEGAL:
            return self._rejected(
                command.kind,
                "unlisted_operation_transition",
                None,
                None,
                OperationState.PENDING_POLICY,
                None,
            )
        existing = uow.operations.get(operation.operation_id)
        if existing is not None:
            if (
                existing.state is OperationState.PENDING_POLICY
                and existing.version == INITIAL_OPERATION_VERSION
                and existing.intent.intent_digest == operation.intent.intent_digest
            ):
                return self._already(
                    command.kind,
                    existing,
                    None,
                    OperationState.PENDING_POLICY,
                    existing.version,
                )
            if existing.intent.intent_digest != operation.intent.intent_digest:
                return self._rejected(
                    command.kind,
                    "intent_conflict",
                    existing,
                    existing.state,
                    OperationState.PENDING_POLICY,
                    existing.version,
                )
            return self._rejected(
                command.kind,
                "operation_id_reused",
                existing,
                existing.state,
                OperationState.PENDING_POLICY,
                existing.version,
            )
        other = uow.operations.get_by_idempotency_identity(
            operation.idempotency_identity
        )
        if other is not None and other.operation_id != operation.operation_id:
            return self._rejected(
                command.kind,
                "intent_conflict",
                other,
                other.state,
                OperationState.PENDING_POLICY,
                other.version,
            )
        uow.operations.insert(operation)
        created = build_audit_event(
            audit_event_id=command.created_audit_event_id,
            operation_id=operation.operation_id,
            sequence=INITIAL_AUDIT_SEQUENCE,
            event_type=AuditEventType.OPERATION_CREATED,
            from_state=None,
            to_state=OperationState.PENDING_POLICY,
            operation_version=INITIAL_OPERATION_VERSION,
            actor=command.actor,
            reason_code=command.reason_code,
            data=_audit_data(kind=command.kind),
            correlation_id=command.correlation_id,
            created_at=command.occurred_at,
        )
        uow.audit_events.append(created)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=command.kind,
            operation=operation,
            compensation=None,
            audit_events=(created,),
            outbox_event=None,
            from_state=None,
            to_state=OperationState.PENDING_POLICY,
            operation_version=INITIAL_OPERATION_VERSION,
        )

    def _apply_claim_compensation(
        self, uow: UnitOfWork, command: ClaimCompensationExecution
    ) -> TransitionResult:
        loaded = uow.operations.get_for_update(command.operation_id)
        if loaded is None:
            raise NotFoundError("operation not found")
        if loaded.version != command.expected_operation_version:
            raise ConcurrencyConflictError("stale operation version")
        if loaded.state is not OperationState.COMPENSATING:
            return self._rejected(
                command.kind,
                "source_state_mismatch",
                loaded,
                loaded.state,
                OperationState.COMPENSATING,
                loaded.version,
                compensation=None,
            )
        compensation = uow.compensations.get(command.compensation_id)
        if compensation is None:
            return self._rejected(
                command.kind,
                "compensation_missing",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
            )
        if compensation.original_operation_id != loaded.operation_id:
            return self._rejected(
                command.kind,
                "compensation_parent_inconsistent",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if (
            compensation.state is CompensationState.EXECUTING
            and compensation.version == command.expected_compensation_version + 1
        ):
            return self._already(
                command.kind,
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version != command.expected_compensation_version:
            raise ConcurrencyConflictError("stale compensation version")
        attempts = tuple(
            uow.compensation_attempts.list_for_compensation(
                compensation.compensation_id
            )
        )
        reason = evaluate_claim_compensation_preconditions(
            command,
            operation=loaded,
            compensation=compensation,
            existing_attempts=attempts,
        )
        if reason is not None:
            return self._rejected(
                command.kind,
                reason,
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        uow.compensation_attempts.insert(command.attempt)
        new_compensation = replace_compensation(
            compensation,
            state=CompensationState.EXECUTING,
            version=next_version(compensation.version),
            updated_at=command.occurred_at,
        )
        uow.compensations.update_cas(
            command.expected_compensation_version, new_compensation
        )
        sequence = uow.audit_events.next_sequence(loaded.operation_id)
        attempted = self._event(
            audit_event_id=command.attempt_audit_event_id,
            operation_id=loaded.operation_id,
            sequence=sequence,
            event_type=AuditEventType.COMPENSATION_ATTEMPTED,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
            actor=command.actor,
            reason_code=command.reason_code,
            data=_audit_data(
                kind=command.kind,
                compensation_id=compensation.compensation_id,
                compensation_attempt_id=command.attempt.compensation_attempt_id,
            ),
            correlation_id=command.correlation_id,
            created_at=command.occurred_at,
        )
        uow.audit_events.append(attempted)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=command.kind,
            operation=loaded,
            compensation=new_compensation,
            audit_events=(attempted,),
            outbox_event=None,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
        )

    def _apply_start_compensation_verification(
        self, uow: UnitOfWork, command: StartCompensationVerification
    ) -> TransitionResult:
        loaded = uow.operations.get_for_update(command.operation_id)
        if loaded is None:
            raise NotFoundError("operation not found")
        if loaded.version != command.expected_operation_version:
            raise ConcurrencyConflictError("stale operation version")
        if loaded.state is not OperationState.COMPENSATING:
            return self._rejected(
                command.kind,
                "source_state_mismatch",
                loaded,
                loaded.state,
                OperationState.COMPENSATING,
                loaded.version,
            )
        compensation = uow.compensations.get(command.compensation_id)
        if compensation is None:
            return self._rejected(
                command.kind,
                "compensation_missing",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
            )
        if compensation.original_operation_id != loaded.operation_id:
            return self._rejected(
                command.kind,
                "compensation_parent_inconsistent",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version == command.expected_compensation_version + 1:
            if compensation.state is CompensationState.VERIFYING:
                return self._already(
                    command.kind,
                    loaded,
                    loaded.state,
                    loaded.state,
                    loaded.version,
                    compensation=compensation,
                )
            return self._rejected(
                command.kind,
                "idempotent_mismatch",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version != command.expected_compensation_version:
            raise ConcurrencyConflictError("stale compensation version")
        attempts = tuple(
            uow.compensation_attempts.list_for_compensation(
                compensation.compensation_id
            )
        )
        loaded_attempt = attempts[-1] if attempts else None
        reason = evaluate_start_compensation_verification_preconditions(
            command,
            operation=loaded,
            compensation=compensation,
            loaded_attempt=loaded_attempt,
        )
        if reason is not None:
            return self._rejected(
                command.kind,
                reason,
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        completed = command.completed_compensation_attempt
        if (
            completed is not None
            and loaded_attempt is not None
            and loaded_attempt.state is AttemptState.STARTED
        ):
            uow.compensation_attempts.complete(completed)
        uow.verifications.insert_request(command.verification_request)
        new_compensation = replace_compensation(
            compensation,
            state=CompensationState.VERIFYING,
            version=next_version(compensation.version),
            updated_at=command.occurred_at,
        )
        uow.compensations.update_cas(
            command.expected_compensation_version, new_compensation
        )
        sequence = uow.audit_events.next_sequence(loaded.operation_id)
        if completed is not None:
            attempt_audit_event_id = command.attempt_audit_event_id
            if attempt_audit_event_id is None:
                raise ValueError(
                    "attempt_audit_event_id is required when completing an attempt"
                )
            event = self._event(
                audit_event_id=attempt_audit_event_id,
                operation_id=loaded.operation_id,
                sequence=sequence,
                event_type=AuditEventType.COMPENSATION_RESULT,
                from_state=OperationState.COMPENSATING,
                to_state=OperationState.COMPENSATING,
                operation_version=loaded.version,
                actor=command.actor,
                reason_code=command.reason_code,
                data=_audit_data(
                    kind=command.kind,
                    compensation_id=compensation.compensation_id,
                    compensation_attempt_id=completed.compensation_attempt_id,
                    effect_outcome=completed.outcome,
                ),
                correlation_id=command.correlation_id,
                created_at=command.occurred_at,
            )
        else:
            event = self._event(
                audit_event_id=command.verification_audit_event_id,
                operation_id=loaded.operation_id,
                sequence=sequence,
                event_type=AuditEventType.COMPENSATION_ATTEMPTED,
                from_state=OperationState.COMPENSATING,
                to_state=OperationState.COMPENSATING,
                operation_version=loaded.version,
                actor=command.actor,
                reason_code=command.reason_code,
                data=_audit_data(
                    kind=command.kind,
                    compensation_id=compensation.compensation_id,
                    verification_id=command.verification_request.verification_id,
                ),
                correlation_id=command.correlation_id,
                created_at=command.occurred_at,
            )
        uow.audit_events.append(event)
        outbox_event = build_outbox_event(
            event_id=command.outbox_event_id,
            operation_id=loaded.operation_id,
            operation_version=loaded.version,
            command=WorkCommand.VERIFY,
            created_at=command.occurred_at,
            correlation_id=command.correlation_id,
        )
        uow.outbox_events.insert(outbox_event)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=command.kind,
            operation=loaded,
            compensation=new_compensation,
            audit_events=(event,),
            outbox_event=outbox_event,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
        )

    def _apply_claim_compensation_retry_attempt(
        self, uow: UnitOfWork, command: ClaimCompensationRetryAttempt
    ) -> TransitionResult:
        loaded = uow.operations.get_for_update(command.operation_id)
        if loaded is None:
            raise NotFoundError("operation not found")
        if loaded.version != command.expected_operation_version:
            raise ConcurrencyConflictError("stale operation version")
        if loaded.state is not OperationState.COMPENSATING:
            return self._rejected(
                command.kind,
                "source_state_mismatch",
                loaded,
                loaded.state,
                OperationState.COMPENSATING,
                loaded.version,
            )
        compensation = uow.compensations.get(command.compensation_id)
        if compensation is None:
            return self._rejected(
                command.kind,
                "compensation_missing",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
            )
        if compensation.original_operation_id != loaded.operation_id:
            return self._rejected(
                command.kind,
                "compensation_parent_inconsistent",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version == command.expected_compensation_version + 1:
            attempts = tuple(
                uow.compensation_attempts.list_for_compensation(
                    compensation.compensation_id
                )
            )
            latest = attempts[-1] if attempts else None
            if (
                latest is not None
                and latest.state is AttemptState.STARTED
                and latest.compensation_attempt_id
                == command.attempt.compensation_attempt_id
            ):
                return self._already(
                    command.kind,
                    loaded,
                    loaded.state,
                    loaded.state,
                    loaded.version,
                    compensation=compensation,
                )
            return self._rejected(
                command.kind,
                "idempotent_mismatch",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version != command.expected_compensation_version:
            raise ConcurrencyConflictError("stale compensation version")
        attempts = tuple(
            uow.compensation_attempts.list_for_compensation(
                compensation.compensation_id
            )
        )
        reason = evaluate_claim_compensation_retry_attempt_preconditions(
            command,
            operation=loaded,
            compensation=compensation,
            existing_attempts=attempts,
        )
        if reason is not None:
            return self._rejected(
                command.kind,
                reason,
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        uow.compensation_attempts.insert(command.attempt)
        new_compensation = replace_compensation(
            compensation,
            state=CompensationState.EXECUTING,
            version=next_version(compensation.version),
            updated_at=command.occurred_at,
        )
        uow.compensations.update_cas(
            command.expected_compensation_version, new_compensation
        )
        sequence = uow.audit_events.next_sequence(loaded.operation_id)
        attempted = self._event(
            audit_event_id=command.attempt_audit_event_id,
            operation_id=loaded.operation_id,
            sequence=sequence,
            event_type=AuditEventType.COMPENSATION_ATTEMPTED,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
            actor=command.actor,
            reason_code=command.reason_code,
            data=_audit_data(
                kind=command.kind,
                compensation_id=compensation.compensation_id,
                compensation_attempt_id=command.attempt.compensation_attempt_id,
            ),
            correlation_id=command.correlation_id,
            created_at=command.occurred_at,
        )
        uow.audit_events.append(attempted)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=command.kind,
            operation=loaded,
            compensation=new_compensation,
            audit_events=(attempted,),
            outbox_event=None,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
        )

    def _apply_retry_compensation_after_verification(
        self, uow: UnitOfWork, command: RetryCompensationAfterVerification
    ) -> TransitionResult:
        loaded = uow.operations.get_for_update(command.operation_id)
        if loaded is None:
            raise NotFoundError("operation not found")
        if loaded.version != command.expected_operation_version:
            raise ConcurrencyConflictError("stale operation version")
        if loaded.state is not OperationState.COMPENSATING:
            return self._rejected(
                command.kind,
                "source_state_mismatch",
                loaded,
                loaded.state,
                OperationState.COMPENSATING,
                loaded.version,
            )
        compensation = uow.compensations.get(command.compensation_id)
        if compensation is None:
            return self._rejected(
                command.kind,
                "compensation_missing",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
            )
        if compensation.original_operation_id != loaded.operation_id:
            return self._rejected(
                command.kind,
                "compensation_parent_inconsistent",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version == command.expected_compensation_version + 1:
            attempts = tuple(
                uow.compensation_attempts.list_for_compensation(
                    compensation.compensation_id
                )
            )
            latest = attempts[-1] if attempts else None
            if (
                latest is not None
                and latest.state is AttemptState.STARTED
                and latest.compensation_attempt_id
                == command.attempt.compensation_attempt_id
            ):
                return self._already(
                    command.kind,
                    loaded,
                    loaded.state,
                    loaded.state,
                    loaded.version,
                    compensation=compensation,
                )
            return self._rejected(
                command.kind,
                "idempotent_mismatch",
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if compensation.version != command.expected_compensation_version:
            raise ConcurrencyConflictError("stale compensation version")
        attempts = tuple(
            uow.compensation_attempts.list_for_compensation(
                compensation.compensation_id
            )
        )
        existing = uow.verifications.get(command.verification_result.verification_id)
        reason = evaluate_retry_compensation_after_verification_preconditions(
            command,
            operation=loaded,
            compensation=compensation,
            existing_attempts=attempts,
            existing_verification=existing,
        )
        if reason is not None:
            return self._rejected(
                command.kind,
                reason,
                loaded,
                loaded.state,
                loaded.state,
                loaded.version,
                compensation=compensation,
            )
        if existing is not None and existing[1] is None:
            uow.verifications.complete(command.verification_result)
        uow.compensation_attempts.insert(command.attempt)
        new_compensation = replace_compensation(
            compensation,
            state=CompensationState.EXECUTING,
            version=next_version(compensation.version),
            updated_at=command.occurred_at,
        )
        uow.compensations.update_cas(
            command.expected_compensation_version, new_compensation
        )
        sequence = uow.audit_events.next_sequence(loaded.operation_id)
        verification_event = self._event(
            audit_event_id=command.verification_audit_event_id,
            operation_id=loaded.operation_id,
            sequence=sequence,
            event_type=AuditEventType.VERIFICATION_COMPLETED,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
            actor=command.actor,
            reason_code=command.reason_code,
            data=_audit_data(
                kind=command.kind,
                verification_id=command.verification_result.verification_id,
                effect_outcome=command.verification_result.outcome,
            ),
            correlation_id=command.correlation_id,
            created_at=command.occurred_at,
        )
        sequence += 1
        attempted = self._event(
            audit_event_id=command.attempt_audit_event_id,
            operation_id=loaded.operation_id,
            sequence=sequence,
            event_type=AuditEventType.COMPENSATION_ATTEMPTED,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
            actor=command.actor,
            reason_code=command.reason_code,
            data=_audit_data(
                kind=command.kind,
                compensation_id=compensation.compensation_id,
                compensation_attempt_id=command.attempt.compensation_attempt_id,
            ),
            correlation_id=command.correlation_id,
            created_at=command.occurred_at,
        )
        uow.audit_events.append(verification_event)
        uow.audit_events.append(attempted)
        outbox_event = build_outbox_event(
            event_id=command.outbox_event_id,
            operation_id=loaded.operation_id,
            operation_version=loaded.version,
            command=WorkCommand.COMPENSATE,
            created_at=command.occurred_at,
            correlation_id=command.correlation_id,
        )
        uow.outbox_events.insert(outbox_event)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=command.kind,
            operation=loaded,
            compensation=new_compensation,
            audit_events=(verification_event, attempted),
            outbox_event=outbox_event,
            from_state=OperationState.COMPENSATING,
            to_state=OperationState.COMPENSATING,
            operation_version=loaded.version,
        )

    def _apply_operation(
        self, uow: UnitOfWork, command: TransitionCommand
    ) -> TransitionResult:
        assert not isinstance(
            command,
            (
                CreateOperation,
                ClaimCompensationExecution,
                StartCompensationVerification,
                ClaimCompensationRetryAttempt,
                RetryCompensationAfterVerification,
            ),
        )
        kind = command.kind
        assert isinstance(kind, TransitionKind)
        source, target = KIND_TO_EDGE[kind]
        loaded = uow.operations.get_for_update(command.operation_id)
        if loaded is None:
            raise NotFoundError("operation not found")
        if loaded.version == command.expected_version + 1:
            if loaded.state is target:
                return self._already(
                    kind,
                    loaded,
                    source,
                    target,
                    loaded.version,
                )
            return self._rejected(
                kind,
                "idempotent_mismatch",
                loaded,
                loaded.state,
                target,
                loaded.version,
            )
        if loaded.version != command.expected_version:
            raise ConcurrencyConflictError("stale operation version")
        if loaded.state is not source:
            return self._rejected(
                kind,
                "source_state_mismatch",
                loaded,
                loaded.state,
                target,
                loaded.version,
            )
        if loaded.state in ABSOLUTE_TERMINAL_STATES:
            return self._rejected(
                kind,
                "absolute_terminal",
                loaded,
                loaded.state,
                target,
                loaded.version,
            )
        listed = evaluate_operation_transition(loaded.state, target)
        if listed.verdict is not TransitionVerdict.LEGAL:
            return self._rejected(
                kind,
                "unlisted_operation_transition",
                loaded,
                loaded.state,
                target,
                loaded.version,
            )
        related = self._load_related(uow, command, loaded)
        reason = evaluate_preconditions(command, operation=loaded, related=related)
        if reason is not None:
            return self._rejected(
                kind,
                reason,
                loaded,
                loaded.state,
                target,
                loaded.version,
                compensation=related.compensation,
            )
        new_version = next_version(loaded.version)
        new_compensation = self._write_related(
            uow, command, loaded, related, new_version
        )
        new_operation = self._replace_for_kind(command, loaded, target, new_version)
        uow.operations.update_cas(command.expected_version, new_operation)
        audits = self._append_audits(
            uow, command, loaded, new_operation, related, new_compensation
        )
        outbox = self._insert_outbox(uow, command, new_operation)
        return TransitionResult(
            outcome=TransitionOutcome.APPLIED,
            reason_code="applied",
            kind=kind,
            operation=new_operation,
            compensation=new_compensation,
            audit_events=audits,
            outbox_event=outbox,
            from_state=source,
            to_state=target,
            operation_version=new_version,
        )

    def _load_related(
        self,
        uow: UnitOfWork,
        command: TransitionCommand,
        operation: Operation,
    ) -> RelatedRecords:
        existing_approval = None
        approval = getattr(command, "approval", None)
        if approval is not None:
            existing_approval = uow.approvals.get(approval.approval_id)
        attempts = tuple(uow.attempts.list_for_operation(operation.operation_id))
        loaded_attempt = None
        if operation.latest_attempt_id is not None:
            loaded_attempt = uow.attempts.get(operation.latest_attempt_id)
        existing_verification_result = None
        if operation.latest_verification_id is not None:
            pair = uow.verifications.get(operation.latest_verification_id)
            if pair is not None:
                existing_verification_result = pair[1]
        compensation = None
        compensation_attempts: tuple[CompensationAttempt, ...] = ()
        loaded_compensation_attempt = None
        if operation.compensation_id is not None:
            compensation = uow.compensations.get(operation.compensation_id)
            if compensation is not None:
                compensation_attempts = tuple(
                    uow.compensation_attempts.list_for_compensation(
                        compensation.compensation_id
                    )
                )
                if compensation_attempts:
                    loaded_compensation_attempt = compensation_attempts[-1]
        existing_compensation_verification = None
        if isinstance(
            command,
            (
                CompensationApplied,
                CompensationOutcomeUnknown,
                CompensationOutcomeFailed,
                CompensationUnknownApplied,
                CompensationUnknownFailed,
                CompensationEscalate,
                CompensationUnknownEscalate,
            ),
        ):
            compensation_verification_result = command.verification_result
            if compensation_verification_result is not None:
                pair = uow.verifications.get(
                    compensation_verification_result.verification_id
                )
                if pair is not None:
                    existing_compensation_verification = pair
        return RelatedRecords(
            existing_approval=existing_approval,
            attempts=attempts,
            loaded_attempt=loaded_attempt,
            existing_verification_result=existing_verification_result,
            compensation=compensation,
            compensation_attempts=compensation_attempts,
            loaded_compensation_attempt=loaded_compensation_attempt,
            existing_compensation_verification=existing_compensation_verification,
        )

    def _write_related(
        self,
        uow: UnitOfWork,
        command: TransitionCommand,
        operation: Operation,
        related: RelatedRecords,
        _new_version: int,
    ) -> Compensation | None:
        kind = command.kind
        compensation = related.compensation
        if isinstance(command, (PolicyAllow, PolicyDeny, PolicyRequireApproval)):
            uow.policy_decisions.insert(command.policy_decision)
        if isinstance(command, PolicyRequireApproval):
            uow.approvals.insert(command.approval)
        if isinstance(command, (ApprovalGrant, ApprovalReject, CancelAwaitingApproval)):
            uow.approvals.update_cas_state(command.approval, ApprovalState.PENDING)
        if isinstance(command, ClaimExecution):
            uow.attempts.insert(command.attempt)
        if isinstance(
            command,
            (
                ExecutionApplied,
                ExecutionRequireVerification,
                ExecutionNotAppliedRetry,
                ExecutionNotAppliedFail,
                ExecutionUnknown,
            ),
        ):
            completed = getattr(command, "completed_attempt", None)
            if (
                completed is not None
                and related.loaded_attempt is not None
                and related.loaded_attempt.state is AttemptState.STARTED
            ):
                uow.attempts.complete(completed)
        if isinstance(
            command,
            (
                ExecutionRequireVerification,
                UnknownStartVerification,
                ManualStartVerification,
            ),
        ):
            uow.verifications.insert_request(command.verification_request)
        if isinstance(
            command,
            (
                VerificationApplied,
                VerificationNotAppliedRetry,
                VerificationNotAppliedFail,
                VerificationInconclusive,
                VerificationEscalate,
            ),
        ):
            result = getattr(command, "verification_result", None)
            if result is not None and related.existing_verification_result is None:
                uow.verifications.complete(result)
        if isinstance(command, (UnknownReconcileApplied, UnknownReconcileNotApplied)):
            uow.reconciliation_decisions.insert(command.reconciliation)
        if isinstance(
            command,
            (
                SucceededStartCompensation,
                FailedStartCompensation,
                ManualStartCompensation,
            ),
        ):
            uow.compensations.insert(command.compensation)
            compensation = command.compensation
        if isinstance(
            command,
            (
                CompensationApplied,
                CompensationOutcomeUnknown,
                CompensationOutcomeFailed,
                CompensationUnknownApplied,
                CompensationUnknownFailed,
            ),
        ):
            completed = command.completed_compensation_attempt
            if (
                completed is not None
                and related.loaded_compensation_attempt is not None
                and related.loaded_compensation_attempt.state is AttemptState.STARTED
            ):
                uow.compensation_attempts.complete(completed)
        if isinstance(
            command,
            (
                CompensationApplied,
                CompensationOutcomeUnknown,
                CompensationOutcomeFailed,
                CompensationUnknownApplied,
                CompensationUnknownFailed,
                CompensationEscalate,
                CompensationUnknownEscalate,
            ),
        ):
            verification_result = command.verification_result
            if verification_result is not None and (
                related.existing_compensation_verification is not None
                and related.existing_compensation_verification[1] is None
            ):
                uow.verifications.complete(verification_result)
        if (
            isinstance(kind, TransitionKind)
            and kind in COMPENSATION_TARGET_STATE
            and compensation is not None
        ):
            new_state = COMPENSATION_TARGET_STATE[kind]
            new_compensation = replace_compensation(
                compensation,
                state=new_state,
                version=next_version(compensation.version),
                updated_at=command.occurred_at,
            )
            uow.compensations.update_cas(compensation.version, new_compensation)
            return new_compensation
        if kind in ESCALATE_KINDS:
            return compensation
        return compensation

    def _replace_for_kind(
        self,
        command: TransitionCommand,
        loaded: Operation,
        target: OperationState,
        new_version: int,
    ) -> Operation:
        kwargs: dict[str, object] = {}
        if isinstance(command, (PolicyAllow, PolicyDeny, PolicyRequireApproval)):
            kwargs["current_policy_decision_id"] = (
                command.policy_decision.policy_decision_id
            )
        if isinstance(command, PolicyRequireApproval):
            kwargs["current_approval_id"] = command.approval.approval_id
        if isinstance(command, (ApprovalGrant, ApprovalReject, CancelAwaitingApproval)):
            kwargs["current_approval_id"] = command.approval.approval_id
        if isinstance(command, ClaimExecution):
            kwargs["latest_attempt_id"] = command.attempt.attempt_id
        if isinstance(
            command,
            (
                ExecutionRequireVerification,
                UnknownStartVerification,
                ManualStartVerification,
            ),
        ):
            kwargs["latest_verification_id"] = (
                command.verification_request.verification_id
            )
        if isinstance(
            command,
            (
                SucceededStartCompensation,
                FailedStartCompensation,
                ManualStartCompensation,
            ),
        ):
            kwargs["compensation_id"] = command.compensation.compensation_id
        return replace_operation(
            loaded,
            state=target,
            version=new_version,
            updated_at=command.occurred_at,
            **kwargs,  # type: ignore[arg-type]
        )

    def _append_audits(
        self,
        uow: UnitOfWork,
        command: TransitionCommand,
        loaded: Operation,
        new_operation: Operation,
        related: RelatedRecords,
        new_compensation: Compensation | None,
    ) -> tuple[AuditEvent, ...]:
        assert not isinstance(command, (CreateOperation, ClaimCompensationExecution))
        assert isinstance(command.kind, TransitionKind)
        sequence = uow.audit_events.next_sequence(loaded.operation_id)
        events: list[AuditEvent] = []
        source, target = KIND_TO_EDGE[command.kind]
        actor = command.actor
        occurred_at = command.occurred_at
        version = new_operation.version
        data_kind = _audit_data(kind=command.kind)

        def add(
            audit_event_id: OpaqueId,
            event_type: AuditEventType,
            data: JsonValue,
            *,
            from_state: OperationState | None = source,
            to_state: OperationState | None = target,
        ) -> None:
            nonlocal sequence
            event = self._event(
                audit_event_id=audit_event_id,
                operation_id=loaded.operation_id,
                sequence=sequence,
                event_type=event_type,
                from_state=from_state,
                to_state=to_state,
                operation_version=version,
                actor=actor,
                reason_code=command.reason_code,
                data=data,
                correlation_id=command.correlation_id,
                created_at=occurred_at,
            )
            events.append(event)
            sequence += 1

        if isinstance(command, (PolicyAllow, PolicyDeny, PolicyRequireApproval)):
            add(
                command.policy_audit_event_id,
                AuditEventType.POLICY_EVALUATED,
                _audit_data(
                    kind=command.kind,
                    policy_decision_id=command.policy_decision.policy_decision_id,
                ),
            )
        if isinstance(command, PolicyRequireApproval):
            add(
                command.approval_audit_event_id,
                AuditEventType.APPROVAL_REQUESTED,
                _audit_data(
                    kind=command.kind,
                    approval_id=command.approval.approval_id,
                    policy_decision_id=command.policy_decision.policy_decision_id,
                ),
            )
        if isinstance(command, (ApprovalGrant, ApprovalReject)):
            add(
                command.approval_audit_event_id,
                AuditEventType.APPROVAL_DECIDED,
                _audit_data(
                    kind=command.kind, approval_id=command.approval.approval_id
                ),
            )
        if isinstance(command, ClaimExecution):
            add(
                command.attempt_audit_event_id,
                AuditEventType.EXECUTION_ATTEMPT_STARTED,
                _audit_data(kind=command.kind, attempt_id=command.attempt.attempt_id),
            )
        if isinstance(
            command,
            (
                ExecutionApplied,
                ExecutionRequireVerification,
                ExecutionNotAppliedRetry,
                ExecutionNotAppliedFail,
                ExecutionUnknown,
            ),
        ):
            crash = None
            outcome = None
            attempt_id = None
            if (
                isinstance(command, ExecutionUnknown)
                and command.completed_attempt is None
            ):
                crash = interpret_execution_crash(
                    operation_state=OperationState.EXECUTING,
                    attempt_state=AttemptState.STARTED,
                ).interpretation
                if related.loaded_attempt is not None:
                    attempt_id = related.loaded_attempt.attempt_id
            else:
                completed = command.completed_attempt
                if completed is not None:
                    outcome = completed.outcome
                    attempt_id = completed.attempt_id
            add(
                command.evidence_audit_event_id,
                AuditEventType.EXECUTION_EVIDENCE_RECORDED,
                _audit_data(
                    kind=command.kind,
                    attempt_id=attempt_id,
                    effect_outcome=outcome,
                    crash_interpretation=crash,
                ),
            )
        if isinstance(command, ExecutionRequireVerification):
            add(
                command.verification_audit_event_id,
                AuditEventType.VERIFICATION_STARTED,
                _audit_data(
                    kind=command.kind,
                    verification_id=command.verification_request.verification_id,
                ),
            )
        if isinstance(
            command,
            (
                VerificationApplied,
                VerificationNotAppliedRetry,
                VerificationNotAppliedFail,
                VerificationInconclusive,
            ),
        ):
            add(
                command.verification_audit_event_id,
                AuditEventType.VERIFICATION_COMPLETED,
                _audit_data(
                    kind=command.kind,
                    verification_id=command.verification_result.verification_id,
                    effect_outcome=command.verification_result.outcome,
                ),
            )
        if isinstance(command, UnknownStartVerification):
            add(
                command.verification_audit_event_id,
                AuditEventType.VERIFICATION_STARTED,
                _audit_data(
                    kind=command.kind,
                    verification_id=command.verification_request.verification_id,
                ),
            )
        if isinstance(command, (UnknownReconcileApplied, UnknownReconcileNotApplied)):
            add(
                command.reconciliation_audit_event_id,
                AuditEventType.RECONCILIATION_DECIDED,
                _audit_data(
                    kind=command.kind,
                    reconciliation_decision_id=command.reconciliation.reconciliation_decision_id,
                ),
            )
        if isinstance(command, (SucceededStartCompensation, FailedStartCompensation)):
            add(
                command.compensation_audit_event_id,
                AuditEventType.COMPENSATION_REQUESTED,
                _audit_data(
                    kind=command.kind,
                    compensation_id=command.compensation.compensation_id,
                ),
            )
        if isinstance(
            command,
            (
                CompensationApplied,
                CompensationOutcomeUnknown,
                CompensationOutcomeFailed,
            ),
        ):
            attempt = command.completed_compensation_attempt
            add(
                command.compensation_result_audit_event_id,
                AuditEventType.COMPENSATION_RESULT,
                _audit_data(
                    kind=command.kind,
                    compensation_id=loaded.compensation_id,
                    compensation_attempt_id=None
                    if attempt is None
                    else attempt.compensation_attempt_id,
                    effect_outcome=None if attempt is None else attempt.outcome,
                ),
            )
        if isinstance(command, ManualStartVerification):
            add(
                command.operator_audit_event_id,
                AuditEventType.OPERATOR_ACTION,
                data_kind,
            )
            add(
                command.verification_audit_event_id,
                AuditEventType.VERIFICATION_STARTED,
                _audit_data(
                    kind=command.kind,
                    verification_id=command.verification_request.verification_id,
                ),
            )
        if isinstance(command, ManualStartCompensation):
            add(
                command.operator_audit_event_id,
                AuditEventType.OPERATOR_ACTION,
                data_kind,
            )
            add(
                command.compensation_audit_event_id,
                AuditEventType.COMPENSATION_REQUESTED,
                _audit_data(
                    kind=command.kind,
                    compensation_id=command.compensation.compensation_id,
                ),
            )
        if isinstance(command, ManualSafeRetry):
            add(
                command.operator_audit_event_id,
                AuditEventType.OPERATOR_ACTION,
                data_kind,
            )
        manual_id = getattr(command, "manual_audit_event_id", None)
        if manual_id is not None:
            add(
                manual_id,
                AuditEventType.MANUAL_INTERVENTION_REASON,
                data_kind,
            )
        transition_data = data_kind
        if isinstance(command, CancelAwaitingApproval):
            transition_data = _audit_data(
                kind=command.kind, approval_id=command.approval.approval_id
            )
        add(
            command.transition_audit_event_id,
            AuditEventType.OPERATION_TRANSITIONED,
            transition_data,
        )
        for event in events:
            uow.audit_events.append(event)
        return tuple(events)

    def _insert_outbox(
        self,
        uow: UnitOfWork,
        command: TransitionCommand,
        new_operation: Operation,
    ) -> OutboxEvent | None:
        if not isinstance(command.kind, TransitionKind):
            return None
        mapped = OUTBOX_COMMAND_FOR_KIND.get(command.kind)
        if mapped is None:
            return None
        event_id = getattr(command, "outbox_event_id", None)
        if not isinstance(event_id, OpaqueId):
            return None
        event = build_outbox_event(
            event_id=event_id,
            operation_id=new_operation.operation_id,
            operation_version=new_operation.version,
            command=mapped,
            created_at=command.occurred_at,
            correlation_id=command.correlation_id,
        )
        uow.outbox_events.insert(event)
        return event

    def _event(
        self,
        *,
        audit_event_id: OpaqueId,
        operation_id: OpaqueId,
        sequence: int,
        event_type: AuditEventType,
        from_state: OperationState | None,
        to_state: OperationState | None,
        operation_version: int,
        actor: PrincipalRef | None,
        reason_code: str,
        data: JsonValue,
        correlation_id: str | None,
        created_at: UtcTimestamp,
    ) -> AuditEvent:
        return build_audit_event(
            audit_event_id=audit_event_id,
            operation_id=operation_id,
            sequence=sequence,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            operation_version=operation_version,
            actor=actor,
            reason_code=reason_code,
            data=data,
            correlation_id=correlation_id,
            created_at=created_at,
        )

    def _rejected(
        self,
        kind: TransitionKind | CompensationProgressKind,
        reason_code: str,
        operation: Operation | None,
        from_state: OperationState | None,
        to_state: OperationState | None,
        operation_version: int | None,
        compensation: Compensation | None = None,
    ) -> TransitionResult:
        return TransitionResult(
            outcome=TransitionOutcome.REJECTED,
            reason_code=reason_code,
            kind=kind,
            operation=operation,
            compensation=compensation,
            audit_events=(),
            outbox_event=None,
            from_state=from_state,
            to_state=to_state,
            operation_version=operation_version,
        )

    def _already(
        self,
        kind: TransitionKind | CompensationProgressKind,
        operation: Operation,
        from_state: OperationState | None,
        to_state: OperationState | None,
        operation_version: int,
        compensation: Compensation | None = None,
    ) -> TransitionResult:
        return TransitionResult(
            outcome=TransitionOutcome.ALREADY_APPLIED,
            reason_code="already_applied",
            kind=kind,
            operation=operation,
            compensation=compensation,
            audit_events=(),
            outbox_event=None,
            from_state=from_state,
            to_state=to_state,
            operation_version=operation_version,
        )
