"""Scan EXECUTING, then VERIFYING, then UNKNOWN with a fresh list after each group."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.persistence.uow import unit_of_work
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.clock import Clock
from stateback.recovery.commands import RECOVERY_ACTOR, RecoveryCommand, ScanCommand
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.recover import recover_unknown_operation
from stateback.recovery.results import RecoveryResult
from stateback.transitions.service import TransitionService


def scan_recoverable(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ScanCommand,
    crash_after: RecoveryCrashPoint | None,
) -> tuple[RecoveryResult, ...]:
    actor = command.actor if command.actor is not None else RECOVERY_ACTOR
    results: list[RecoveryResult] = []
    with unit_of_work(uow_factory) as uow:
        executing = uow.operations.list_by_state(OperationState.EXECUTING)
    for op in executing:
        ids = command.ids_for.for_operation(op.operation_id)
        results.append(
            recover_unknown_operation(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                command=RecoveryCommand(
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    ids=ids,
                    actor=actor,
                    correlation_id=command.correlation_id,
                ),
                crash_after=crash_after,
            )
        )
    with unit_of_work(uow_factory) as uow:
        verifying = uow.operations.list_by_state(OperationState.VERIFYING)
    for op in verifying:
        ids = command.ids_for.for_operation(op.operation_id)
        results.append(
            recover_unknown_operation(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                command=RecoveryCommand(
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    ids=ids,
                    actor=actor,
                    correlation_id=command.correlation_id,
                ),
                crash_after=crash_after,
            )
        )
    with unit_of_work(uow_factory) as uow:
        unknown = uow.operations.list_by_state(OperationState.UNKNOWN)
    for op in unknown:
        ids = command.ids_for.for_operation(op.operation_id)
        results.append(
            recover_unknown_operation(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                command=RecoveryCommand(
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    ids=ids,
                    actor=actor,
                    correlation_id=command.correlation_id,
                ),
                crash_after=crash_after,
            )
        )
    return tuple(results)
