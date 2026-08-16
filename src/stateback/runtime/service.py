"""In-process synchronous execution kernel facade."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.policy.protocol import PolicyEngine
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.runtime.commands import ExecuteCommand, RecoverCommand, SubmitCommand
from stateback.runtime.execute import execute_operation
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.ids import ExecuteIds
from stateback.runtime.recover import recover_operation
from stateback.runtime.results import RuntimeDisposition, RuntimeResult
from stateback.runtime.submit import submit_operation
from stateback.transitions.service import TransitionService


class SynchronousRuntime:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        registry: CapabilityRegistry,
        policy_engine: PolicyEngine,
        clock: Clock,
        transitions: TransitionService | None = None,
        crash_after: RuntimeCrashPoint | None = None,
    ) -> None:
        self._factory = session_factory
        self._registry = registry
        self._policy = policy_engine
        self._clock = clock
        self._transitions = (
            transitions if transitions is not None else TransitionService()
        )
        self._crash_after = crash_after

    def maybe_crash(self, point: RuntimeCrashPoint) -> None:
        from stateback.runtime.faults import maybe_crash as _maybe_crash

        _maybe_crash(self._crash_after, point)

    def submit(self, command: SubmitCommand) -> RuntimeResult:
        return submit_operation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            policy_engine=self._policy,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def execute(self, command: ExecuteCommand) -> RuntimeResult:
        return execute_operation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
        )

    def recover(self, command: RecoverCommand) -> RuntimeResult:
        return recover_operation(
            uow_factory=self._factory,
            transitions=self._transitions,
            registry=self._registry,
            clock=self._clock,
            command=command,
            crash_after=self._crash_after,
            policy_engine=self._policy,
        )

    def run(
        self,
        submit: SubmitCommand,
        execute_ids: ExecuteIds,
    ) -> RuntimeResult:
        submitted = self.submit(submit)
        if submitted.disposition is not RuntimeDisposition.ACCEPTED:
            return submitted
        assert submitted.operation is not None
        if submitted.operation.state is not OperationState.READY:
            return submitted
        return self.execute(
            ExecuteCommand(
                operation_id=submitted.operation.operation_id,
                expected_version=submitted.operation.version,
                ids=execute_ids,
                actor=submit.requester,
                correlation_id=submit.correlation_id,
            )
        )
