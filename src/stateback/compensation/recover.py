"""Recover `COMPENSATING` leftovers, `COMPENSATION_UNKNOWN`, and terminals (§11.17).

Does not re-invoke `adapter.compensate` for durable evidence that already has
an outcome; only calls a provider when a fresh attempt is genuinely claimed
(E42 verify path, `verification_mode is NONE` retry, leftover-STARTED never
calls `compensate` again per §11.17.2).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    COMPENSATION_ACTOR,
    ExecuteCompensationCommand,
    RecoverCompensationCommand,
)
from stateback.compensation.execute import (
    build_compensate_outcome_command,
    execute_compensation,
    find_pending_compensation_verification,
    run_compensate_from_attempt,
    run_verify_cycle,
)
from stateback.compensation.faults import CompensationCrashPoint, maybe_crash
from stateback.compensation.outcome import decide_compensate_kind
from stateback.compensation.persist import (
    list_compensation_attempts,
    list_verifications,
    load_compensation,
    load_operation,
    load_policy,
)
from stateback.compensation.request import (
    build_compensation_verification_request,
    build_started_attempt,
)
from stateback.compensation.results import (
    CompensationDisposition,
    CompensationResult,
    make_compensation_result,
)
from stateback.domain.capability import EffectDescriptor
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    AttemptState,
    CompensationState,
    EffectOutcome,
    OperationState,
    RetrySafetyVerdict,
    VerificationMode,
    VerificationTarget,
)
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyDecision
from stateback.domain.refs import PrincipalRef
from stateback.persistence.exceptions import ConcurrencyConflictError, PersistenceError
from stateback.persistence.uow import unit_of_work
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.runtime.outcome import max_automatic_attempts
from stateback.transitions.commands import (
    ClaimCompensationRetryAttempt,
    CompensationOutcomeUnknown,
    CompensationUnknownEscalate,
    CompensationUnknownRetry,
    StartCompensationVerification,
)
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService


def recover_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
) -> CompensationResult:
    op = load_operation(uow_factory, command.operation_id)
    actor = command.actor if command.actor is not None else COMPENSATION_ACTOR
    if op.state is OperationState.COMPENSATED:
        return make_compensation_result(
            CompensationDisposition.ACCEPTED, "already_applied", operation=op
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
    if op.state is OperationState.COMPENSATION_FAILED:
        return make_compensation_result(
            CompensationDisposition.ACCEPTED,
            "already_applied",
            operation=op,
            compensation=compensation,
        )
    if op.version != command.expected_version:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
            operation=op,
            compensation=compensation,
        )
    if op.state is OperationState.COMPENSATING:
        return _recover_compensating(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            compensation=compensation,
            actor=actor,
        )
    if op.state is OperationState.COMPENSATION_UNKNOWN:
        return _recover_unknown(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            compensation=compensation,
            actor=actor,
        )
    return make_compensation_result(
        CompensationDisposition.REJECTED,
        "source_state_mismatch",
        operation=op,
        compensation=compensation,
    )


def _recover_compensating(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
    actor: PrincipalRef,
) -> CompensationResult:
    if compensation.state is CompensationState.PENDING:
        return execute_compensation(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=ExecuteCompensationCommand(
                operation_id=op.operation_id,
                expected_version=op.version,
                ids=command.ids,
                actor=actor,
                correlation_id=command.correlation_id,
            ),
            crash_after=crash_after,
        )
    if compensation.state is CompensationState.EXECUTING:
        attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
        latest = attempts[-1] if attempts else None
        if latest is None:
            return make_compensation_result(
                CompensationDisposition.REJECTED,
                "attempt_missing",
                operation=op,
                compensation=compensation,
            )
        if latest.state is AttemptState.STARTED:
            return _leftover_started_to_unknown(
                uow_factory=uow_factory,
                transitions=transitions,
                clock=clock,
                command=command,
                op=op,
                compensation=compensation,
                actor=actor,
            )
        return _replay_completed_mapper(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            compensation=compensation,
            latest=latest,
            actor=actor,
        )
    if compensation.state is CompensationState.VERIFYING:
        pending = find_pending_compensation_verification(uow_factory, op.operation_id)
        if pending is not None:
            return run_verify_cycle(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                op=op,
                compensation=compensation,
                actor=actor,
                correlation_id=command.correlation_id,
                ids=command.ids,
                crash_after=crash_after,
            )
        rows = list_verifications(uow_factory, op.operation_id)
        completed_rows = [
            pair
            for pair in rows
            if pair[0].target is VerificationTarget.COMPENSATION and pair[1] is not None
        ]
        if not completed_rows:
            return make_compensation_result(
                CompensationDisposition.REJECTED,
                "verification_missing",
                operation=op,
                compensation=compensation,
            )
        _, existing_result = completed_rows[-1]
        return run_verify_cycle(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            op=op,
            compensation=compensation,
            actor=actor,
            correlation_id=command.correlation_id,
            ids=command.ids,
            crash_after=crash_after,
            existing_result=existing_result,
        )
    return make_compensation_result(
        CompensationDisposition.REJECTED,
        "unsupported_state",
        operation=op,
        compensation=compensation,
    )


def _leftover_started_to_unknown(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    clock: Clock,
    command: RecoverCompensationCommand,
    op: Operation,
    compensation: Compensation,
    actor: PrincipalRef,
) -> CompensationResult:
    ids = command.ids
    try:
        with unit_of_work(uow_factory) as uow:
            result = transitions.apply(
                uow,
                CompensationOutcomeUnknown(
                    kind=TransitionKind.COMPENSATION_OUTCOME_UNKNOWN,
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    occurred_at=clock.now(),
                    actor=actor,
                    correlation_id=command.correlation_id,
                    reason_code="compensation_leftover_unknown",
                    transition_audit_event_id=ids.complete_transition_audit_event_id,
                    completed_compensation_attempt=None,
                    compensation_result_audit_event_id=ids.evidence_audit_event_id,
                    outbox_event_id=ids.complete_outbox_event_id,
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
    return make_compensation_result(
        CompensationDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        compensation=result.compensation,
        transition=result,
    )


def _replay_completed_mapper(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
    latest: CompensationAttempt,
    actor: PrincipalRef,
) -> CompensationResult:
    ids = command.ids
    descriptor = registry.descriptor(op.intent.effect)
    policy = load_policy(uow_factory, op)
    if policy is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "policy_missing",
            operation=op,
            compensation=compensation,
        )
    assert latest.outcome is not None
    decision = decide_compensate_kind(
        outcome=latest.outcome, descriptor=descriptor, obligations=policy.obligations
    )
    cmd = build_compensate_outcome_command(
        kind=decision.kind,
        reason_code=decision.reason_code,
        op=op,
        compensation=compensation,
        completed=latest,
        actor=actor,
        correlation_id=command.correlation_id,
        occurred_at=clock.now(),
        ids=ids,
        clock=clock,
        is_retry=latest.attempt_number > 1,
    )
    try:
        with unit_of_work(uow_factory) as uow:
            result = transitions.apply(uow, cmd)
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
    assert result.operation is not None
    assert result.compensation is not None
    if decision.kind is CompensationProgressKind.START_COMPENSATION_VERIFICATION:
        maybe_crash(crash_after, CompensationCrashPoint.AFTER_VERIFY_START_COMMIT)
        return run_verify_cycle(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            op=result.operation,
            compensation=result.compensation,
            actor=actor,
            correlation_id=command.correlation_id,
            ids=ids,
            crash_after=crash_after,
        )
    return make_compensation_result(
        CompensationDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        compensation=result.compensation,
        transition=result,
    )


def _recover_unknown(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
    actor: PrincipalRef,
) -> CompensationResult:
    descriptor = registry.descriptor(op.intent.effect)
    attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
    latest = attempts[-1] if attempts else None
    if latest is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "attempt_missing",
            operation=op,
            compensation=compensation,
        )
    policy = load_policy(uow_factory, op)
    if policy is None:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "policy_missing",
            operation=op,
            compensation=compensation,
        )
    if descriptor.verification_mode is VerificationMode.NONE:
        return _unknown_without_verify(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            compensation=compensation,
            latest=latest,
            actor=actor,
            descriptor=descriptor,
            policy=policy,
        )
    return _unknown_start_verification(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        crash_after=crash_after,
        op=op,
        compensation=compensation,
        latest=latest,
        actor=actor,
    )


def _unknown_without_verify(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
    latest: CompensationAttempt,
    actor: PrincipalRef,
    descriptor: EffectDescriptor,
    policy: PolicyDecision,
) -> CompensationResult:
    ids = command.ids
    outcome = (
        latest.outcome
        if latest.state is AttemptState.COMPLETED
        else EffectOutcome.UNKNOWN
    )
    attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
    first_started_at = attempts[0].started_at
    retry = registry.evaluate_retry_safety(
        effect=op.intent.effect,
        execution_outcome=outcome,
        verification_outcome=None,
        now=clock.now(),
        first_attempt_at=first_started_at,
    )
    cap = max_automatic_attempts(policy.obligations)
    if retry.verdict is RetrySafetyVerdict.SAFE and latest.attempt_number < cap:
        next_attempt_number = latest.attempt_number + 1
        retry_ids = ids.retry_ids_for.for_attempt(
            compensation.compensation_id, next_attempt_number
        )
        next_attempt = build_started_attempt(
            compensation_id=compensation.compensation_id,
            attempt_id=retry_ids.attempt_id,
            attempt_number=next_attempt_number,
            descriptor=descriptor,
            clock=clock,
        )
        try:
            with unit_of_work(uow_factory) as uow:
                retry_result: TransitionResult = transitions.apply(
                    uow,
                    CompensationUnknownRetry(
                        kind=TransitionKind.COMPENSATION_UNKNOWN_RETRY,
                        operation_id=op.operation_id,
                        expected_version=op.version,
                        occurred_at=clock.now(),
                        actor=COMPENSATION_ACTOR,
                        correlation_id=command.correlation_id,
                        reason_code=retry.reason_code,
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
                            kind=(
                                CompensationProgressKind.CLAIM_COMPENSATION_RETRY_ATTEMPT
                            ),
                            operation_id=retry_result.operation.operation_id,
                            expected_operation_version=retry_result.operation.version,
                            compensation_id=retry_result.compensation.compensation_id,
                            expected_compensation_version=(
                                retry_result.compensation.version
                            ),
                            attempt=next_attempt,
                            occurred_at=clock.now(),
                            actor=COMPENSATION_ACTOR,
                            correlation_id=command.correlation_id,
                            reason_code="compensation_retry_claimed",
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
        if claim_result.outcome is TransitionOutcome.ALREADY_APPLIED:
            fresh_op = load_operation(uow_factory, op.operation_id)
            return recover_compensation(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                command=RecoverCompensationCommand(
                    operation_id=fresh_op.operation_id,
                    expected_version=fresh_op.version,
                    ids=ids,
                    actor=actor,
                    correlation_id=command.correlation_id,
                ),
                crash_after=crash_after,
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
            actor=COMPENSATION_ACTOR,
            correlation_id=command.correlation_id,
            ids=ids,
            crash_after=crash_after,
        )
    reason = (
        "compensation_attempt_budget_exhausted"
        if retry.verdict is RetrySafetyVerdict.SAFE
        else "unknown_without_verification"
    )
    try:
        with unit_of_work(uow_factory) as uow:
            result = transitions.apply(
                uow,
                CompensationUnknownEscalate(
                    kind=TransitionKind.COMPENSATION_UNKNOWN_ESCALATE,
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    occurred_at=clock.now(),
                    actor=COMPENSATION_ACTOR,
                    correlation_id=command.correlation_id,
                    reason_code=reason,
                    transition_audit_event_id=ids.complete_transition_audit_event_id,
                    manual_audit_event_id=ids.manual_audit_event_id,
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
    return make_compensation_result(
        CompensationDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        compensation=result.compensation,
        transition=result,
    )


def _unknown_start_verification(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoverCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
    latest: CompensationAttempt,
    actor: PrincipalRef,
) -> CompensationResult:
    ids = command.ids
    retry_ids = ids.retry_ids_for.for_attempt(
        compensation.compensation_id, latest.attempt_number + 1
    )
    try:
        with unit_of_work(uow_factory) as uow:
            retry_result: TransitionResult = transitions.apply(
                uow,
                CompensationUnknownRetry(
                    kind=TransitionKind.COMPENSATION_UNKNOWN_RETRY,
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    occurred_at=clock.now(),
                    actor=actor,
                    correlation_id=command.correlation_id,
                    reason_code="unknown_verification_supported",
                    transition_audit_event_id=(
                        retry_ids.parent_retry_transition_audit_event_id
                    ),
                    outbox_event_id=retry_ids.parent_retry_outbox_event_id,
                ),
            )
            if retry_result.outcome is not TransitionOutcome.APPLIED:
                started_result = retry_result
            else:
                assert retry_result.operation is not None
                assert retry_result.compensation is not None
                request = build_compensation_verification_request(
                    operation=retry_result.operation,
                    compensation=retry_result.compensation,
                    attempt=latest,
                    verification_id=retry_ids.resume_verification_id,
                    clock=clock,
                )
                started_result = transitions.apply(
                    uow,
                    StartCompensationVerification(
                        kind=CompensationProgressKind.START_COMPENSATION_VERIFICATION,
                        operation_id=retry_result.operation.operation_id,
                        expected_operation_version=retry_result.operation.version,
                        compensation_id=retry_result.compensation.compensation_id,
                        expected_compensation_version=(
                            retry_result.compensation.version
                        ),
                        completed_compensation_attempt=None,
                        verification_request=request,
                        occurred_at=clock.now(),
                        actor=actor,
                        correlation_id=command.correlation_id,
                        reason_code="unknown_verification_supported",
                        attempt_audit_event_id=None,
                        verification_audit_event_id=(
                            retry_ids.resume_verification_start_audit_event_id
                        ),
                        outbox_event_id=(retry_ids.resume_verification_outbox_event_id),
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
            "persist_failed",
            operation=failed_op,
        )
    if started_result.outcome is TransitionOutcome.REJECTED:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            started_result.reason_code,
            operation=started_result.operation,
            compensation=started_result.compensation,
            transition=started_result,
        )
    if started_result.outcome is TransitionOutcome.ALREADY_APPLIED:
        fresh_op = load_operation(uow_factory, op.operation_id)
        return recover_compensation(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=RecoverCompensationCommand(
                operation_id=fresh_op.operation_id,
                expected_version=fresh_op.version,
                ids=ids,
                actor=actor,
                correlation_id=command.correlation_id,
            ),
            crash_after=crash_after,
        )
    assert started_result.operation is not None
    assert started_result.compensation is not None
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_VERIFY_START_COMMIT)
    return run_verify_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        op=started_result.operation,
        compensation=started_result.compensation,
        actor=actor,
        correlation_id=command.correlation_id,
        ids=ids,
        crash_after=crash_after,
    )
