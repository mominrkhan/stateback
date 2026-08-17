"""In-process verification/reconciliation service facade."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.clock import Clock
from stateback.recovery.commands import (
    OperatorVerificationCommand,
    RecoveryCommand,
    ScanCommand,
)
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.operator import start_operator_verification
from stateback.recovery.recover import recover_unknown_operation
from stateback.recovery.results import RecoveryResult
from stateback.recovery.scan import scan_recoverable
from stateback.transitions.service import TransitionService


class RecoveryService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        registry: CapabilityRegistry,
        clock: Clock,
        transitions: TransitionService | None = None,
        crash_after: RecoveryCrashPoint | None = None,
    ) -> None:
        self._factory = session_factory
        self._registry = registry
        self._clock = clock
        self._transitions = (
            transitions if transitions is not None else TransitionService()
        )
        self._crash_after = crash_after

    def recover(self, command: RecoveryCommand) -> RecoveryResult:
        return recover_unknown_operation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def scan(self, command: ScanCommand) -> tuple[RecoveryResult, ...]:
        return scan_recoverable(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def start_operator_verification(
        self, command: OperatorVerificationCommand
    ) -> RecoveryResult:
        return start_operator_verification(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )
