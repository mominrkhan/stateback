"""Scan `COMPENSATING`, then `COMPENSATION_UNKNOWN`, with a fresh list after each group (E36, §11.18)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    COMPENSATION_ACTOR,
    RecoverCompensationCommand,
    ScanCompensationCommand,
)
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.recover import recover_compensation
from stateback.compensation.results import CompensationResult
from stateback.domain.enums import OperationState
from stateback.persistence.uow import unit_of_work
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.transitions.service import TransitionService

_SCAN_STATES = (OperationState.COMPENSATING, OperationState.COMPENSATION_UNKNOWN)


def scan_compensations(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ScanCompensationCommand,
    crash_after: CompensationCrashPoint | None,
) -> tuple[CompensationResult, ...]:
    actor = command.actor if command.actor is not None else COMPENSATION_ACTOR
    results: list[CompensationResult] = []
    for state in _SCAN_STATES:
        with unit_of_work(uow_factory) as uow:
            operations = uow.operations.list_by_state(state)
        if command.limit is not None:
            operations = operations[: command.limit]
        for op in operations:
            ids = command.ids_for.for_operation(op.operation_id)
            results.append(
                recover_compensation(
                    uow_factory=uow_factory,
                    transitions=transitions,
                    registry=registry,
                    clock=clock,
                    command=RecoverCompensationCommand(
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
