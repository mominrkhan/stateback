"""Operator-started verification from MANUAL_INTERVENTION."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, VerificationMode
from stateback.persistence.exceptions import (
    ConcurrencyConflictError,
    NotFoundError,
    PersistenceError,
)
from stateback.persistence.uow import unit_of_work
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.clock import Clock
from stateback.recovery.commands import OperatorVerificationCommand, RecoveryCommand
from stateback.recovery.faults import RecoveryCrashPoint, maybe_crash
from stateback.recovery.recover import run_verifying_cycle
from stateback.recovery.request import build_original_verification_request
from stateback.recovery.results import (
    RecoveryDisposition,
    RecoveryResult,
    make_recovery_result,
)
from stateback.runtime.execute import load_operation
from stateback.transitions.commands import ManualStartVerification
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService


def start_operator_verification(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: OperatorVerificationCommand,
    crash_after: RecoveryCrashPoint | None,
) -> RecoveryResult:
    try:
        op = load_operation(uow_factory, command.operation_id)
    except NotFoundError:
        return make_recovery_result(RecoveryDisposition.REJECTED, "not_found")
    if op.state is not OperationState.MANUAL_INTERVENTION:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "source_state_mismatch",
            operation=op,
        )
    descriptor = registry.descriptor(op.intent.effect)
    if descriptor.verification_mode is VerificationMode.NONE:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "verification_unsupported",
            operation=op,
        )
    with unit_of_work(uow_factory) as uow:
        attempts = uow.attempts.list_for_operation(op.operation_id)
    attempt = attempts[-1] if attempts else None
    ids = command.ids
    request = build_original_verification_request(
        operation=op,
        attempt=attempt,
        verification_id=ids.verification_id,
        requested_at=clock.now(),
    )
    try:
        with unit_of_work(uow_factory) as uow:
            applied = transitions.apply(
                uow,
                ManualStartVerification(
                    kind=TransitionKind.MANUAL_START_VERIFICATION,
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    occurred_at=clock.now(),
                    actor=command.actor,
                    correlation_id=command.correlation_id,
                    reason_code="manual_start_verification",
                    transition_audit_event_id=ids.start_transition_audit_event_id,
                    verification_request=request,
                    operator_audit_event_id=ids.manual_audit_event_id,
                    verification_audit_event_id=ids.verification_start_audit_event_id,
                    outbox_event_id=ids.start_outbox_event_id,
                ),
            )
    except NotFoundError:
        return make_recovery_result(RecoveryDisposition.REJECTED, "not_found")
    except ConcurrencyConflictError:
        return make_recovery_result(
            RecoveryDisposition.INFRASTRUCTURE_FAILURE,
            "stale_version",
            operation=op,
        )
    except PersistenceError:
        return make_recovery_result(
            RecoveryDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed",
            operation=op,
        )
    if applied.outcome is TransitionOutcome.REJECTED:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            applied.reason_code,
            operation=applied.operation,
            transition=applied,
        )
    if applied.outcome is TransitionOutcome.ALREADY_APPLIED:
        reloaded = load_operation(uow_factory, command.operation_id)
        return run_verifying_cycle(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=_as_recovery_command(command),
            crash_after=crash_after,
            op=reloaded,
            actor=command.actor,
        )
    assert applied.operation is not None
    maybe_crash(crash_after, RecoveryCrashPoint.AFTER_START_COMMIT)
    return run_verifying_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=_as_recovery_command(command),
        crash_after=crash_after,
        op=applied.operation,
        actor=command.actor,
    )


def _as_recovery_command(command: OperatorVerificationCommand) -> RecoveryCommand:
    return RecoveryCommand(
        operation_id=command.operation_id,
        expected_version=command.expected_version,
        ids=command.ids,
        actor=command.actor,
        correlation_id=command.correlation_id,
    )
