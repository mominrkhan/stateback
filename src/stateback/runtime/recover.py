"""Recover durable in-flight or incomplete execution without calling execute."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.crash import interpret_execution_crash
from stateback.domain.enums import (
    AttemptState,
    CrashInterpretation,
    OperationState,
    PrincipalType,
)
from stateback.domain.operation import Operation
from stateback.domain.refs import PrincipalRef
from stateback.persistence.uow import unit_of_work
from stateback.policy.protocol import PolicyEngine
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.runtime.commands import RecoverCommand
from stateback.runtime.exceptions import StatebackRuntimeError
from stateback.runtime.execute import (
    _evidence_from_attempt,
    _latest_attempt,
    apply_execution_kind_from_ids,
    load_operation,
)
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.results import (
    RuntimeDisposition,
    RuntimeResult,
    make_result,
)
from stateback.transitions.commands import ExecutionUnknown
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService

RECOVERY_ACTOR = PrincipalRef(
    type=PrincipalType.SERVICE,
    id="stateback.runtime",
    display_name="SynchronousRuntime",
)

_RECOVER_ALREADY = frozenset(
    {
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.DENIED,
        OperationState.CANCELLED,
        OperationState.UNKNOWN,
        OperationState.VERIFYING,
        OperationState.AWAITING_APPROVAL,
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATED,
        OperationState.COMPENSATION_FAILED,
        OperationState.MANUAL_INTERVENTION,
    }
)


def recover_operation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCommand,
    crash_after: RuntimeCrashPoint | None,
    policy_engine: PolicyEngine,
) -> RuntimeResult:
    del crash_after
    del policy_engine
    op = load_operation(uow_factory, command.operation_id)
    actor = command.actor if command.actor is not None else RECOVERY_ACTOR
    if op.state is OperationState.PENDING_POLICY:
        return make_result(
            RuntimeDisposition.REJECTED,
            "not_ready",
            operation=op,
        )
    if op.state is OperationState.READY:
        return make_result(
            RuntimeDisposition.ACCEPTED,
            "accepted",
            operation=op,
        )
    if op.state is OperationState.EXECUTING:
        attempt = _latest_attempt(uow_factory, op)
        if attempt is None:
            return make_result(
                RuntimeDisposition.REJECTED,
                "unsupported_state",
                operation=op,
            )
        if attempt.state is AttemptState.STARTED:
            return _unknown_without_completing(
                uow_factory=uow_factory,
                transitions=transitions,
                clock=clock,
                command=command,
                op=op,
                actor=actor,
            )
        if attempt.state is AttemptState.COMPLETED:
            return apply_execution_kind_from_ids(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                operation=op,
                completed=attempt,
                actor=actor,
                correlation_id=command.correlation_id,
                ids=command.ids,
                evidence=_evidence_from_attempt(attempt),
            )
        return make_result(
            RuntimeDisposition.REJECTED,
            "unsupported_state",
            operation=op,
        )
    if op.state in _RECOVER_ALREADY:
        return make_result(
            RuntimeDisposition.ACCEPTED,
            "already_applied",
            operation=op,
        )
    return make_result(
        RuntimeDisposition.REJECTED,
        "unsupported_state",
        operation=op,
    )


def _unknown_without_completing(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    clock: Clock,
    command: RecoverCommand,
    op: Operation,
    actor: PrincipalRef,
) -> RuntimeResult:
    crash = interpret_execution_crash(
        operation_state=OperationState.EXECUTING,
        attempt_state=AttemptState.STARTED,
    )
    if crash.interpretation is not CrashInterpretation.POTENTIALLY_UNKNOWN:
        raise StatebackRuntimeError(
            "illegal_combination",
            "EXECUTING+STARTED must interpret as POTENTIALLY_UNKNOWN",
        )
    ids = command.ids
    with unit_of_work(uow_factory) as uow:
        result = transitions.apply(
            uow,
            ExecutionUnknown(
                kind=TransitionKind.EXECUTION_UNKNOWN,
                operation_id=op.operation_id,
                expected_version=op.version,
                occurred_at=clock.now(),
                actor=actor,
                correlation_id=command.correlation_id,
                reason_code="execution_unknown",
                transition_audit_event_id=ids.execution_transition_audit_event_id,
                completed_attempt=None,
                evidence_audit_event_id=ids.evidence_audit_event_id,
                outbox_event_id=ids.execution_outbox_event_id,
            ),
        )
    if result.outcome is TransitionOutcome.REJECTED:
        return make_result(
            RuntimeDisposition.REJECTED,
            result.reason_code,
            operation=result.operation,
            transition=result,
        )
    return make_result(
        RuntimeDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        transition=result,
    )
