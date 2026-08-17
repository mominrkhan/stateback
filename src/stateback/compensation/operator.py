"""Operator-initiated compensation start, retry, and escalation (§11.19)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    OperatorCompensationCommand,
    StartCompensationCommand,
)
from stateback.compensation.execute import run_compensate_from_attempt
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.persist import (
    list_compensation_attempts,
    load_compensation,
    load_operation,
)
from stateback.compensation.request import build_started_attempt
from stateback.compensation.results import (
    CompensationDisposition,
    CompensationResult,
    make_compensation_result,
)
from stateback.compensation.start import start_compensation
from stateback.domain.enums import OperationState
from stateback.domain.secrets import key_is_forbidden, value_is_forbidden
from stateback.persistence.exceptions import ConcurrencyConflictError, PersistenceError
from stateback.persistence.uow import unit_of_work
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.transitions.commands import (
    ClaimCompensationRetryAttempt,
    CompensationEscalate,
    CompensationFailedEscalate,
    CompensationFailedRetry,
    CompensationUnknownEscalate,
)
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService


def start_operator_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: OperatorCompensationCommand,
    crash_after: CompensationCrashPoint | None,
) -> CompensationResult:
    invalid = _validate_reason_code(command)
    if invalid is not None:
        return invalid
    return start_compensation(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=StartCompensationCommand(
            operation_id=command.operation_id,
            expected_version=command.expected_version,
            ids=command.ids,
            actor=command.actor,
            correlation_id=command.correlation_id,
            automatic=False,
        ),
        crash_after=crash_after,
        operator=True,
        reason_code=command.reason_code,
    )


def retry_failed_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: OperatorCompensationCommand,
    crash_after: CompensationCrashPoint | None,
) -> CompensationResult:
    invalid = _validate_reason_code(command)
    if invalid is not None:
        return invalid
    op = load_operation(uow_factory, command.operation_id)
    if op.version != command.expected_version:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
            operation=op,
        )
    if op.state is not OperationState.COMPENSATION_FAILED:
        return make_compensation_result(
            CompensationDisposition.REJECTED, "source_state_mismatch", operation=op
        )
    if op.compensation_id is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED, "compensation_missing", operation=op
        )
    compensation = load_compensation(uow_factory, op.compensation_id)
    if compensation is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED, "compensation_missing", operation=op
        )
    descriptor = registry.descriptor(op.intent.effect)
    attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
    next_attempt_number = len(attempts) + 1
    retry_ids = command.ids.retry_ids_for.for_attempt(
        compensation.compensation_id, next_attempt_number
    )
    next_attempt = build_started_attempt(
        compensation_id=compensation.compensation_id,
        attempt_id=retry_ids.attempt_id,
        attempt_number=next_attempt_number,
        descriptor=descriptor,
        clock=clock,
    )
    ids = command.ids
    try:
        with unit_of_work(uow_factory) as uow:
            retry_result: TransitionResult = transitions.apply(
                uow,
                CompensationFailedRetry(
                    kind=TransitionKind.COMPENSATION_FAILED_RETRY,
                    operation_id=op.operation_id,
                    expected_version=command.expected_version,
                    occurred_at=clock.now(),
                    actor=command.actor,
                    correlation_id=command.correlation_id,
                    reason_code=command.reason_code,
                    transition_audit_event_id=(
                        retry_ids.parent_retry_transition_audit_event_id
                    ),
                    outbox_event_id=retry_ids.parent_retry_outbox_event_id,
                ),
            )
            if retry_result.outcome is not TransitionOutcome.APPLIED:
                claim_result = retry_result
            else:
                assert retry_result.operation is not None
                assert retry_result.compensation is not None
                claim_result = transitions.apply(
                    uow,
                    ClaimCompensationRetryAttempt(
                        kind=CompensationProgressKind.CLAIM_COMPENSATION_RETRY_ATTEMPT,
                        operation_id=retry_result.operation.operation_id,
                        expected_operation_version=retry_result.operation.version,
                        compensation_id=retry_result.compensation.compensation_id,
                        expected_compensation_version=(
                            retry_result.compensation.version
                        ),
                        attempt=next_attempt,
                        occurred_at=clock.now(),
                        actor=command.actor,
                        correlation_id=command.correlation_id,
                        reason_code=command.reason_code,
                        attempt_audit_event_id=retry_ids.attempt_audit_event_id,
                    ),
                )
    except ConcurrencyConflictError:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
            operation=op,
            compensation=compensation,
        )
    except PersistenceError:
        failed_op = load_operation(uow_factory, op.operation_id)
        return make_compensation_result(
            CompensationDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed_before_compensate",
            operation=failed_op,
        )
    if claim_result.outcome is TransitionOutcome.REJECTED:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            claim_result.reason_code,
            operation=claim_result.operation,
            compensation=claim_result.compensation,
            transition=claim_result,
        )
    assert claim_result.operation is not None
    assert claim_result.compensation is not None
    return run_compensate_from_attempt(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        op=claim_result.operation,
        compensation=claim_result.compensation,
        attempt=next_attempt,
        actor=command.actor,
        correlation_id=command.correlation_id,
        ids=ids,
        crash_after=crash_after,
    )


def escalate_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    clock: Clock,
    command: OperatorCompensationCommand,
) -> CompensationResult:
    invalid = _validate_reason_code(command)
    if invalid is not None:
        return invalid
    op = load_operation(uow_factory, command.operation_id)
    if op.version != command.expected_version:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
            operation=op,
        )
    ids = command.ids
    if op.state is OperationState.COMPENSATING:
        cmd: (
            CompensationEscalate
            | CompensationUnknownEscalate
            | CompensationFailedEscalate
        ) = CompensationEscalate(
            kind=TransitionKind.COMPENSATION_ESCALATE,
            operation_id=op.operation_id,
            expected_version=command.expected_version,
            occurred_at=clock.now(),
            actor=command.actor,
            correlation_id=command.correlation_id,
            reason_code=command.reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            manual_audit_event_id=ids.manual_audit_event_id,
        )
    elif op.state is OperationState.COMPENSATION_UNKNOWN:
        cmd = CompensationUnknownEscalate(
            kind=TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
            operation_id=op.operation_id,
            expected_version=command.expected_version,
            occurred_at=clock.now(),
            actor=command.actor,
            correlation_id=command.correlation_id,
            reason_code=command.reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            manual_audit_event_id=ids.manual_audit_event_id,
        )
    elif op.state is OperationState.COMPENSATION_FAILED:
        cmd = CompensationFailedEscalate(
            kind=TransitionKind.COMPENSATION_FAILED_ESCALATE,
            operation_id=op.operation_id,
            expected_version=command.expected_version,
            occurred_at=clock.now(),
            actor=command.actor,
            correlation_id=command.correlation_id,
            reason_code=command.reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            manual_audit_event_id=ids.manual_audit_event_id,
        )
    else:
        return make_compensation_result(
            CompensationDisposition.REJECTED, "source_state_mismatch", operation=op
        )
    try:
        with unit_of_work(uow_factory) as uow:
            result = transitions.apply(uow, cmd)
    except ConcurrencyConflictError:
        return make_compensation_result(
            CompensationDisposition.REJECTED, "concurrency_conflict", operation=op
        )
    except PersistenceError:
        failed_op = load_operation(uow_factory, op.operation_id)
        return make_compensation_result(
            CompensationDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed",
            operation=failed_op,
        )
    if result.outcome is TransitionOutcome.REJECTED:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            result.reason_code,
            operation=result.operation,
            compensation=result.compensation,
            transition=result,
        )
    reason_code = (
        "already_applied"
        if result.outcome is TransitionOutcome.ALREADY_APPLIED
        else "accepted"
    )
    return make_compensation_result(
        CompensationDisposition.ACCEPTED,
        reason_code,
        operation=result.operation,
        compensation=result.compensation,
        transition=result,
    )


def _validate_reason_code(
    command: OperatorCompensationCommand,
) -> CompensationResult | None:
    if command.actor is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "actor_required",
        )
    if key_is_forbidden(command.reason_code) or value_is_forbidden(command.reason_code):
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "secret_field",
        )
    return None
