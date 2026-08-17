"""In-process compensation service facade (§11.20)."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    ExecuteCompensationCommand,
    OperatorCompensationCommand,
    RecoverCompensationCommand,
    ScanCompensationCommand,
    StartCompensationCommand,
)
from stateback.compensation.execute import execute_compensation
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.operator import (
    escalate_compensation,
    retry_failed_compensation,
    start_operator_compensation,
)
from stateback.compensation.recover import recover_compensation
from stateback.compensation.results import CompensationResult
from stateback.compensation.scan import scan_compensations
from stateback.compensation.start import start_compensation
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.transitions.service import TransitionService


class CompensationService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        registry: CapabilityRegistry,
        clock: Clock,
        transitions: TransitionService | None = None,
        crash_after: CompensationCrashPoint | None = None,
    ) -> None:
        self._factory = session_factory
        self._registry = registry
        self._clock = clock
        self._transitions = (
            transitions if transitions is not None else TransitionService()
        )
        self._crash_after = crash_after

    def start(self, command: StartCompensationCommand) -> CompensationResult:
        return start_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def execute(self, command: ExecuteCompensationCommand) -> CompensationResult:
        return execute_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def recover(self, command: RecoverCompensationCommand) -> CompensationResult:
        return recover_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def scan(self, command: ScanCompensationCommand) -> tuple[CompensationResult, ...]:
        return scan_compensations(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def start_operator_compensation(
        self, command: OperatorCompensationCommand
    ) -> CompensationResult:
        return start_operator_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def retry_failed_compensation(
        self, command: OperatorCompensationCommand
    ) -> CompensationResult:
        return retry_failed_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def escalate(self, command: OperatorCompensationCommand) -> CompensationResult:
        return escalate_compensation(
            uow_factory=self._factory,
            transitions=self._transitions,
            clock=self._clock,
            command=command,
        )
