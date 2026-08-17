"""PostgreSQL-reloading work dispatcher with bounded ack decisions."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import ExecuteCompensationCommand
from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState, PrincipalType, WorkCommand
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef
from stateback.messaging.codec import decode_work_message
from stateback.messaging.ids import DeterministicWorkIds
from stateback.persistence.exceptions import NotFoundError, PersistenceError
from stateback.recovery.commands import RecoveryCommand
from stateback.recovery.results import RecoveryDisposition
from stateback.recovery.service import RecoveryService
from stateback.runtime.commands import ExecuteCommand, RecoverCommand
from stateback.runtime.execute import load_operation
from stateback.runtime.results import RuntimeDisposition
from stateback.runtime.service import SynchronousRuntime

WORKER_ACTOR = PrincipalRef(
    type=PrincipalType.SERVICE,
    id="stateback.worker",
    display_name="StatebackWorker",
)


class AckDecision(StrEnum):
    ACK = "ACK"
    NAK = "NAK"
    TERM = "TERM"


class WorkHandler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        runtime: SynchronousRuntime,
        recovery: RecoveryService,
        compensation: CompensationService,
        max_deliveries: int,
    ) -> None:
        if max_deliveries < 1:
            raise ValueError("max_deliveries must be >= 1")
        self._factory = session_factory
        self._runtime = runtime
        self._recovery = recovery
        self._compensation = compensation
        self._max_deliveries = max_deliveries

    def handle(self, payload: bytes, *, delivery_count: int) -> AckDecision:
        if delivery_count < 1:
            raise ValueError("delivery_count must be >= 1")
        try:
            message = decode_work_message(payload)
        except ContractValidationError:
            return AckDecision.TERM
        try:
            operation = load_operation(self._factory, message.operation_id)
        except NotFoundError:
            return self._retry_or_term(delivery_count)
        except (PersistenceError, DBAPIError):
            return self._retry_or_term(delivery_count)

        ids = DeterministicWorkIds(message)
        try:
            disposition = self._dispatch(
                message.command,
                operation.state,
                operation.version,
                message.operation_id,
                message.correlation_id,
                ids,
            )
        except (PersistenceError, DBAPIError):
            return self._retry_or_term(delivery_count)
        return (
            self._retry_or_term(delivery_count)
            if disposition == "INFRASTRUCTURE_FAILURE"
            else AckDecision.ACK
        )

    def _dispatch(
        self,
        command: WorkCommand,
        state: OperationState,
        version: int,
        operation_id: OpaqueId,
        correlation_id: str | None,
        ids: DeterministicWorkIds,
    ) -> str:
        if command is WorkCommand.EXECUTE:
            if state is OperationState.READY:
                result = self._runtime.execute(
                    ExecuteCommand(
                        operation_id=operation_id,
                        expected_version=version,
                        ids=ids.execute(),
                        actor=WORKER_ACTOR,
                        correlation_id=correlation_id,
                    )
                )
                return result.disposition.value
            if state is OperationState.EXECUTING:
                result = self._runtime.recover(
                    RecoverCommand(
                        operation_id=operation_id,
                        expected_version=version,
                        ids=ids.runtime_recover(),
                        actor=WORKER_ACTOR,
                        correlation_id=correlation_id,
                    )
                )
                return result.disposition.value
            return RuntimeDisposition.ACCEPTED.value

        if command is WorkCommand.VERIFY:
            if state in {
                OperationState.EXECUTING,
                OperationState.UNKNOWN,
                OperationState.VERIFYING,
            }:
                recovery_result = self._recovery.recover(
                    RecoveryCommand(
                        operation_id=operation_id,
                        expected_version=version,
                        ids=ids.recovery(),
                        actor=WORKER_ACTOR,
                        correlation_id=correlation_id,
                    )
                )
                return recovery_result.disposition.value
            if state in {
                OperationState.COMPENSATING,
                OperationState.COMPENSATION_UNKNOWN,
            }:
                compensation_result = self._compensation.execute(
                    ExecuteCompensationCommand(
                        operation_id=operation_id,
                        expected_version=version,
                        ids=ids.compensation(),
                        actor=WORKER_ACTOR,
                        correlation_id=correlation_id,
                    )
                )
                return compensation_result.disposition.value
            return RecoveryDisposition.ACCEPTED.value

        if state in {
            OperationState.COMPENSATING,
            OperationState.COMPENSATION_UNKNOWN,
            OperationState.COMPENSATION_FAILED,
            OperationState.COMPENSATED,
        }:
            compensation_result = self._compensation.execute(
                ExecuteCompensationCommand(
                    operation_id=operation_id,
                    expected_version=version,
                    ids=ids.compensation(),
                    actor=WORKER_ACTOR,
                    correlation_id=correlation_id,
                )
            )
            return compensation_result.disposition.value
        return CompensationDisposition.ACCEPTED.value

    def _retry_or_term(self, delivery_count: int) -> AckDecision:
        if delivery_count >= self._max_deliveries:
            return AckDecision.TERM
        return AckDecision.NAK
