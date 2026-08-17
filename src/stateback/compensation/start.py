"""Start a compensation from SUCCEEDED / FAILED / MANUAL_INTERVENTION."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import COMPENSATION_ACTOR, StartCompensationCommand
from stateback.compensation.eligibility import evaluate_start_eligibility
from stateback.compensation.faults import CompensationCrashPoint, maybe_crash
from stateback.compensation.ids import CompensationIds
from stateback.compensation.request import build_compensation_record
from stateback.compensation.results import (
    CompensationDisposition,
    CompensationResult,
    make_compensation_result,
)
from stateback.domain.compensation import Compensation
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.persistence.exceptions import ConcurrencyConflictError, NotFoundError
from stateback.persistence.uow import unit_of_work
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.transitions.commands import (
    FailedStartCompensation,
    ManualStartCompensation,
    SucceededStartCompensation,
    TransitionCommand,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService


def start_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: StartCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    operator: bool = False,
    reason_code: str = "compensation_requested",
) -> CompensationResult:
    actor = command.actor if command.actor is not None else COMPENSATION_ACTOR
    try:
        with unit_of_work(uow_factory) as uow:
            op = uow.operations.get_for_update(command.operation_id)
            if op is None:
                raise NotFoundError("operation not found")
            if op.version != command.expected_version:
                raise ConcurrencyConflictError("stale operation version")
            if op.compensation_id is not None:
                compensation = uow.compensations.get(op.compensation_id)
                return make_compensation_result(
                    CompensationDisposition.ACCEPTED,
                    "already_applied",
                    operation=op,
                    compensation=compensation,
                )
            try:
                descriptor = registry.descriptor(op.intent.effect)
            except UnsupportedEffectError:
                return make_compensation_result(
                    CompensationDisposition.REJECTED,
                    "unregistered_effect",
                    operation=op,
                )
            attempts = uow.attempts.list_for_operation(op.operation_id)
            latest_attempt = attempts[-1] if attempts else None
            if op.current_policy_decision_id is None:
                return make_compensation_result(
                    CompensationDisposition.REJECTED,
                    "policy_missing",
                    operation=op,
                )
            policy = uow.policy_decisions.get(op.current_policy_decision_id)
            if policy is None:
                return make_compensation_result(
                    CompensationDisposition.REJECTED,
                    "policy_missing",
                    operation=op,
                )
            eligibility = evaluate_start_eligibility(
                operation=op,
                descriptor=descriptor,
                obligations=policy.obligations,
                latest_original_attempt=latest_attempt,
                automatic=command.automatic,
                operator=operator,
            )
            if not eligibility.allowed:
                return make_compensation_result(
                    CompensationDisposition.NOT_ELIGIBLE,
                    eligibility.reason_code,
                    operation=op,
                )
            compensation = build_compensation_record(
                operation=op,
                descriptor=descriptor,
                ids=command.ids,
                actor=actor,
                clock=clock,
                policy_decision_id=op.current_policy_decision_id,
            )
            assert eligibility.start_kind is not None
            cmd = _start_command(
                kind=eligibility.start_kind,
                operation_id=op.operation_id,
                expected_version=op.version,
                compensation=compensation,
                actor=actor,
                correlation_id=command.correlation_id,
                occurred_at=clock.now(),
                ids=command.ids,
                reason_code=reason_code,
            )
            result = transitions.apply(uow, cmd)
    except ConcurrencyConflictError:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
        )
    if result.outcome is TransitionOutcome.REJECTED:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            result.reason_code,
            operation=result.operation,
            compensation=result.compensation,
            transition=result,
        )
    if result.outcome is TransitionOutcome.ALREADY_APPLIED:
        return make_compensation_result(
            CompensationDisposition.ACCEPTED,
            "already_applied",
            operation=result.operation,
            compensation=result.compensation,
            transition=result,
        )
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_START_COMMIT)
    return make_compensation_result(
        CompensationDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        compensation=result.compensation,
        transition=result,
    )


def _start_command(
    *,
    kind: TransitionKind,
    operation_id: OpaqueId,
    expected_version: int,
    compensation: Compensation,
    actor: PrincipalRef,
    correlation_id: str | None,
    occurred_at: UtcTimestamp,
    ids: CompensationIds,
    reason_code: str,
) -> TransitionCommand:
    if kind is TransitionKind.SUCCEEDED_START_COMPENSATION:
        return SucceededStartCompensation(
            kind=kind,
            operation_id=operation_id,
            expected_version=expected_version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.start_transition_audit_event_id,
            compensation=compensation,
            compensation_audit_event_id=ids.compensation_requested_audit_event_id,
            outbox_event_id=ids.start_outbox_event_id,
        )
    if kind is TransitionKind.FAILED_START_COMPENSATION:
        return FailedStartCompensation(
            kind=kind,
            operation_id=operation_id,
            expected_version=expected_version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.start_transition_audit_event_id,
            compensation=compensation,
            compensation_audit_event_id=ids.compensation_requested_audit_event_id,
            outbox_event_id=ids.start_outbox_event_id,
        )
    assert kind is TransitionKind.MANUAL_START_COMPENSATION
    return ManualStartCompensation(
        kind=kind,
        operation_id=operation_id,
        expected_version=expected_version,
        occurred_at=occurred_at,
        actor=actor,
        correlation_id=correlation_id,
        reason_code=reason_code,
        transition_audit_event_id=ids.start_transition_audit_event_id,
        compensation=compensation,
        compensation_audit_event_id=ids.compensation_requested_audit_event_id,
        outbox_event_id=ids.start_outbox_event_id,
        operator_audit_event_id=ids.operator_audit_event_id,
    )
