"""Drive a compensation through compensate/verify cycles (§11.16-§11.17.5).

`execute_compensation` is the entry point for claim+compensate. The internal
loop (`_run_cycle`) also implements the verify-cycle-after-require-verify
(§11.16.5) and the NOT_APPLIED automatic retry chain (§11.16.6) so that both
`execute.py` and `recover.py` share one state machine: `recover.py` imports
`run_verify_cycle` / `resume_compensate` from here at module load time (no
circular import), while `execute.py` only reaches into `recover.py` through a
deferred import for durable "leftover" shapes that must not re-invoke the
provider (§11.16.1).
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.commands import (
    COMPENSATION_ACTOR,
    ExecuteCompensationCommand,
)
from stateback.compensation.evidence import (
    complete_attempt_from_evidence,
    complete_attempt_from_verification,
)
from stateback.compensation.faults import CompensationCrashPoint, maybe_crash
from stateback.compensation.ids import CompensationIds
from stateback.compensation.kinds import compensation_decision_to_kind
from stateback.compensation.outcome import decide_compensate_kind
from stateback.compensation.persist import (
    list_compensation_attempts,
    list_execution_attempts,
    list_verifications,
    load_compensation,
    load_operation,
    load_policy,
)
from stateback.compensation.reconcile import (
    completed_compensation_verification_count,
    reconcile_compensation,
)
from stateback.compensation.request import (
    build_compensate_context,
    build_compensation_provider_request,
    build_compensation_verification_request,
    build_compensation_verify_context,
    build_started_attempt,
)
from stateback.compensation.results import (
    CompensationDisposition,
    CompensationResult,
    make_compensation_result,
)
from stateback.domain.capability import (
    CompensationEvidence,
    EffectDescriptor,
    VerificationEvidence,
)
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    CompensationState,
    EffectOutcome,
    ErrorKind,
    OperationState,
    RetrySafetyVerdict,
    VerificationTarget,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.exceptions import ConcurrencyConflictError, PersistenceError
from stateback.persistence.uow import unit_of_work
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.runtime.outcome import max_automatic_attempts
from stateback.transitions.commands import (
    ClaimCompensationExecution,
    ClaimCompensationRetryAttempt,
    CompensationApplied,
    CompensationEscalate,
    CompensationFailedRetry,
    CompensationOutcomeFailed,
    CompensationOutcomeUnknown,
    RetryCompensationAfterVerification,
    StartCompensationVerification,
    TransitionCommand,
)
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService

_DELEGATE_TO_RECOVER = frozenset(
    {OperationState.COMPENSATION_UNKNOWN, OperationState.COMPENSATION_FAILED}
)


def execute_compensation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCompensationCommand,
    crash_after: CompensationCrashPoint | None,
) -> CompensationResult:
    op = load_operation(uow_factory, command.operation_id)
    if (
        op.state not in (OperationState.COMPENSATED, OperationState.COMPENSATION_FAILED)
        and op.version != command.expected_version
    ):
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "concurrency_conflict",
            operation=op,
        )
    return dispatch_execute(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        crash_after=crash_after,
        op=op,
    )


def dispatch_execute(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
) -> CompensationResult:
    if op.state is OperationState.COMPENSATED:
        return make_compensation_result(
            CompensationDisposition.ACCEPTED, "already_applied", operation=op
        )
    if op.state not in (
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATION_FAILED,
    ):
        return make_compensation_result(
            CompensationDisposition.REJECTED, "source_state_mismatch", operation=op
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
    if op.state in _DELEGATE_TO_RECOVER:
        return _delegate_to_recover(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
        )
    if compensation.state is CompensationState.PENDING:
        return claim_and_compensate(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            compensation=compensation,
        )
    if compensation.state is CompensationState.EXECUTING:
        attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
        latest = attempts[-1] if attempts else None
        if latest is not None and latest.state is AttemptState.STARTED:
            return make_compensation_result(
                CompensationDisposition.IN_FLIGHT,
                "in_flight",
                operation=op,
                compensation=compensation,
            )
        return _delegate_to_recover(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
        )
    if compensation.state is CompensationState.VERIFYING:
        return _delegate_to_recover(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
        )
    return make_compensation_result(
        CompensationDisposition.REJECTED,
        "unsupported_state",
        operation=op,
        compensation=compensation,
    )


def _delegate_to_recover(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
) -> CompensationResult:
    from stateback.compensation.commands import RecoverCompensationCommand
    from stateback.compensation.recover import recover_compensation

    return recover_compensation(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=RecoverCompensationCommand(
            operation_id=op.operation_id,
            expected_version=op.version,
            ids=command.ids,
            actor=command.actor,
            correlation_id=command.correlation_id,
        ),
        crash_after=crash_after,
    )


def claim_and_compensate(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCompensationCommand,
    crash_after: CompensationCrashPoint | None,
    op: Operation,
    compensation: Compensation,
) -> CompensationResult:
    actor = command.actor if command.actor is not None else COMPENSATION_ACTOR
    ids = command.ids
    try:
        descriptor = registry.descriptor(op.intent.effect)
    except UnsupportedEffectError:
        return make_compensation_result(
            CompensationDisposition.REJECTED,
            "unregistered_effect",
            operation=op,
            compensation=compensation,
        )
    existing_attempts = list_compensation_attempts(
        uow_factory, compensation.compensation_id
    )
    started = build_started_attempt(
        compensation_id=compensation.compensation_id,
        attempt_id=ids.compensation_attempt_id,
        attempt_number=len(existing_attempts) + 1,
        descriptor=descriptor,
        clock=clock,
    )
    try:
        with unit_of_work(uow_factory) as uow:
            claim_result = transitions.apply(
                uow,
                ClaimCompensationExecution(
                    kind=CompensationProgressKind.CLAIM_COMPENSATION_EXECUTION,
                    operation_id=op.operation_id,
                    expected_operation_version=op.version,
                    compensation_id=compensation.compensation_id,
                    expected_compensation_version=compensation.version,
                    attempt=started,
                    occurred_at=clock.now(),
                    actor=actor,
                    correlation_id=command.correlation_id,
                    reason_code="compensation_claimed",
                    attempt_audit_event_id=ids.claim_attempt_audit_event_id,
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
        return dispatch_execute(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=fresh_op,
        )
    assert claim_result.operation is not None
    assert claim_result.compensation is not None
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_CLAIM_COMMIT)
    return _run_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        mode="compensate",
        op=claim_result.operation,
        compensation=claim_result.compensation,
        attempt=started,
        request=None,
        actor=actor,
        correlation_id=command.correlation_id,
        ids=ids,
        crash_after=crash_after,
        descriptor=descriptor,
    )


def run_verify_cycle(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    op: Operation,
    compensation: Compensation,
    actor: PrincipalRef,
    correlation_id: str | None,
    ids: CompensationIds,
    crash_after: CompensationCrashPoint | None,
    existing_result: VerificationResult | None = None,
) -> CompensationResult:
    """Resolve the incomplete `COMPENSATION`-target verification (§11.17.5).

    `existing_result` lets a caller that already has a completed
    `VerificationResult` (§11.17.4, "complete result and no parent terminal
    yet") re-apply the decision without a second `adapter.verify` call
    (FM-009 analog).
    """
    return _run_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        mode="verify",
        op=op,
        compensation=compensation,
        attempt=None,
        request=None,
        actor=actor,
        correlation_id=correlation_id,
        ids=ids,
        crash_after=crash_after,
        descriptor=None,
        existing_result=existing_result,
    )


def run_compensate_from_attempt(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    op: Operation,
    compensation: Compensation,
    attempt: CompensationAttempt,
    actor: PrincipalRef,
    correlation_id: str | None,
    ids: CompensationIds,
    crash_after: CompensationCrashPoint | None,
) -> CompensationResult:
    """Enter the compensate loop with an already-claimed STARTED attempt."""
    return _run_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        mode="compensate",
        op=op,
        compensation=compensation,
        attempt=attempt,
        request=None,
        actor=actor,
        correlation_id=correlation_id,
        ids=ids,
        crash_after=crash_after,
        descriptor=None,
    )


def find_pending_compensation_verification(
    uow_factory: sessionmaker[Session], operation_id: object
) -> tuple[VerificationRequest, VerificationResult | None] | None:
    rows = list_verifications(uow_factory, operation_id)  # type: ignore[arg-type]
    pending = [
        pair
        for pair in rows
        if pair[0].target is VerificationTarget.COMPENSATION and pair[1] is None
    ]
    return pending[-1] if pending else None


def _run_cycle(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    mode: str,
    op: Operation,
    compensation: Compensation,
    attempt: CompensationAttempt | None,
    request: VerificationRequest | None,
    actor: PrincipalRef,
    correlation_id: str | None,
    ids: CompensationIds,
    crash_after: CompensationCrashPoint | None,
    descriptor: EffectDescriptor | None,
    existing_result: VerificationResult | None = None,
) -> CompensationResult:
    current_op, current_compensation = op, compensation
    current_attempt = attempt
    current_request = request
    current_mode = mode
    pending_existing_result = existing_result
    if descriptor is None:
        descriptor = registry.descriptor(current_op.intent.effect)
    while True:
        if current_mode == "compensate":
            assert current_attempt is not None
            step = _compensate_step(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                op=current_op,
                compensation=current_compensation,
                attempt=current_attempt,
                actor=actor,
                correlation_id=correlation_id,
                ids=ids,
                crash_after=crash_after,
                descriptor=descriptor,
            )
        else:
            step = _verify_step(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                op=current_op,
                compensation=current_compensation,
                request=current_request,
                actor=actor,
                correlation_id=correlation_id,
                ids=ids,
                crash_after=crash_after,
                descriptor=descriptor,
                existing_result=pending_existing_result,
            )
            pending_existing_result = None
        if step[0] == "done":
            result = step[1]
            assert isinstance(result, CompensationResult)
            return result
        if step[0] == "compensate":
            _, next_op, next_compensation, next_attempt = step
            assert isinstance(next_op, Operation)
            assert isinstance(next_compensation, Compensation)
            assert isinstance(next_attempt, CompensationAttempt)
            current_op, current_compensation, current_attempt = (
                next_op,
                next_compensation,
                next_attempt,
            )
            current_request = None
            current_mode = "compensate"
            continue
        assert step[0] == "verify"
        _, next_op, next_compensation = step
        assert isinstance(next_op, Operation)
        assert isinstance(next_compensation, Compensation)
        current_op, current_compensation = next_op, next_compensation
        current_attempt = None
        current_request = None
        current_mode = "verify"


def _compensate_step(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    op: Operation,
    compensation: Compensation,
    attempt: CompensationAttempt,
    actor: PrincipalRef,
    correlation_id: str | None,
    ids: CompensationIds,
    crash_after: CompensationCrashPoint | None,
    descriptor: EffectDescriptor,
) -> tuple[object, ...]:
    original_attempts = tuple(list_execution_attempts(uow_factory, op.operation_id))
    request = build_compensation_provider_request(
        operation=op,
        compensation=compensation,
        attempt=attempt,
        original_attempts=original_attempts,
    )
    context = build_compensate_context(
        operation=op,
        attempt=attempt,
        compensation=compensation,
        correlation_id=correlation_id,
    )
    evidence = _call_compensate(registry, op, context, request)
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_COMPENSATE_BEFORE_EVIDENCE)
    completed = complete_attempt_from_evidence(attempt, evidence, clock.now())
    policy = load_policy(uow_factory, op)
    if policy is None:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                "policy_missing",
                operation=op,
                compensation=compensation,
            ),
        )
    decision = decide_compensate_kind(
        outcome=evidence.outcome, descriptor=descriptor, obligations=policy.obligations
    )
    cmd = build_compensate_outcome_command(
        kind=decision.kind,
        reason_code=decision.reason_code,
        op=op,
        compensation=compensation,
        completed=completed,
        actor=actor,
        correlation_id=correlation_id,
        occurred_at=clock.now(),
        ids=ids,
        clock=clock,
        is_retry=attempt.attempt_number > 1,
    )
    try:
        with unit_of_work(uow_factory) as uow:
            result = transitions.apply(uow, cmd)
    except ConcurrencyConflictError:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                "concurrency_conflict",
                operation=op,
                compensation=compensation,
                evidence=evidence,
            ),
        )
    except PersistenceError:
        failed_op = load_operation(uow_factory, op.operation_id)
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.INFRASTRUCTURE_FAILURE,
                "persist_failed_after_compensate",
                operation=failed_op,
                evidence=evidence,
            ),
        )
    if result.outcome is TransitionOutcome.REJECTED:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                result.reason_code,
                operation=result.operation,
                compensation=result.compensation,
                transition=result,
                evidence=evidence,
            ),
        )
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_EVIDENCE_COMMIT)
    assert result.operation is not None
    assert result.compensation is not None
    if decision.kind is CompensationProgressKind.START_COMPENSATION_VERIFICATION:
        maybe_crash(crash_after, CompensationCrashPoint.AFTER_VERIFY_START_COMMIT)
        return ("verify", result.operation, result.compensation)
    if decision.kind is TransitionKind.COMPENSATION_OUTCOME_FAILED:
        retry = _maybe_claim_retry(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            op=result.operation,
            compensation=result.compensation,
            completed=completed,
            correlation_id=correlation_id,
            ids=ids,
            descriptor=descriptor,
        )
        if retry is None:
            return (
                "done",
                make_compensation_result(
                    CompensationDisposition.ACCEPTED,
                    "accepted",
                    operation=result.operation,
                    compensation=result.compensation,
                    transition=result,
                    evidence=evidence,
                ),
            )
        if isinstance(retry, CompensationResult):
            return ("done", retry)
        next_op, next_compensation, next_attempt = retry
        return ("compensate", next_op, next_compensation, next_attempt)
    return (
        "done",
        make_compensation_result(
            CompensationDisposition.ACCEPTED,
            "accepted",
            operation=result.operation,
            compensation=result.compensation,
            transition=result,
            evidence=evidence,
        ),
    )


def _verify_step(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    op: Operation,
    compensation: Compensation,
    request: VerificationRequest | None,
    actor: PrincipalRef,
    correlation_id: str | None,
    ids: CompensationIds,
    crash_after: CompensationCrashPoint | None,
    descriptor: EffectDescriptor,
    existing_result: VerificationResult | None = None,
) -> tuple[object, ...]:
    evidence: VerificationEvidence | None = None
    if existing_result is not None:
        result = existing_result
    else:
        if request is None:
            pending = find_pending_compensation_verification(
                uow_factory, op.operation_id
            )
            if pending is None:
                return (
                    "done",
                    make_compensation_result(
                        CompensationDisposition.REJECTED,
                        "verification_missing",
                        operation=op,
                        compensation=compensation,
                    ),
                )
            request = pending[0]
        context = build_compensation_verify_context(
            operation=op,
            compensation=compensation,
            request=request,
            correlation_id=correlation_id,
        )
        evidence = _call_verify(registry, op, context, request, clock)
        maybe_crash(crash_after, CompensationCrashPoint.AFTER_VERIFY_BEFORE_RESULT)
        result = VerificationResult(
            contract_version=CONTRACT_VERSION,
            verification_id=request.verification_id,
            outcome=evidence.outcome,
            evidence=evidence.evidence,
            error=evidence.error,
            completed_at=clock.now(),
        )
    attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
    latest_attempt = attempts[-1] if attempts else None
    policy = load_policy(uow_factory, op)
    if policy is None:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                "policy_missing",
                operation=op,
                compensation=compensation,
                verification_evidence=evidence,
            ),
        )
    rows = list_verifications(uow_factory, op.operation_id)
    count = completed_compensation_verification_count(rows)
    current_row = next(
        (
            pair
            for pair in rows
            if pair[0].verification_id == result.verification_id
            and pair[0].target is VerificationTarget.COMPENSATION
        ),
        None,
    )
    if current_row is not None and current_row[1] is None:
        count += 1
    latest_outcome_attempt = (
        latest_attempt
        if latest_attempt is not None and latest_attempt.state is AttemptState.COMPLETED
        else None
    )
    decision = reconcile_compensation(
        verification_result=result,
        latest_compensation_attempt=latest_attempt,
        descriptor=descriptor,
        obligations=policy.obligations,
        completed_compensation_verify_count=count,
    )
    mapped = compensation_decision_to_kind(
        parent_state=op.state,
        compensation_state=compensation.state,
        decision=decision,
    )
    completed_for_command: CompensationAttempt | None = None
    next_attempt_for_retry: CompensationAttempt | None = None
    if mapped.kind in (
        TransitionKind.COMPENSATION_APPLIED,
        TransitionKind.COMPENSATION_OUTCOME_FAILED,
    ):
        expected_outcome = (
            EffectOutcome.APPLIED
            if mapped.kind is TransitionKind.COMPENSATION_APPLIED
            else EffectOutcome.NOT_APPLIED
        )
        if latest_outcome_attempt is not None:
            completed_for_command = latest_outcome_attempt
        elif latest_attempt is not None:
            completed_for_command = complete_attempt_from_verification(
                latest_attempt, result, expected_outcome, clock.now()
            )
        else:
            return (
                "done",
                make_compensation_result(
                    CompensationDisposition.REJECTED,
                    "attempt_missing",
                    operation=op,
                    compensation=compensation,
                    verification_evidence=evidence,
                ),
            )
    elif mapped.kind is CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION:
        existing = list_compensation_attempts(uow_factory, compensation.compensation_id)
        retry_ids = ids.retry_ids_for.for_attempt(
            compensation.compensation_id, len(existing) + 1
        )
        next_attempt_for_retry = build_started_attempt(
            compensation_id=compensation.compensation_id,
            attempt_id=retry_ids.attempt_id,
            attempt_number=len(existing) + 1,
            descriptor=descriptor,
            clock=clock,
        )
    cmd = _verify_outcome_command(
        kind=mapped.kind,
        reason_code=mapped.reason_code,
        op=op,
        compensation=compensation,
        verification_result=result,
        completed_for_command=completed_for_command,
        next_attempt=next_attempt_for_retry,
        actor=actor,
        correlation_id=correlation_id,
        occurred_at=clock.now(),
        ids=ids,
        idempotency_mode=descriptor.idempotency_mode,
        current_attempt_number=(
            latest_attempt.attempt_number if latest_attempt is not None else 1
        ),
    )
    try:
        with unit_of_work(uow_factory) as uow:
            applied = transitions.apply(uow, cmd)
    except ConcurrencyConflictError:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                "concurrency_conflict",
                operation=op,
                compensation=compensation,
                verification_evidence=evidence,
            ),
        )
    except PersistenceError:
        failed_op = load_operation(uow_factory, op.operation_id)
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.INFRASTRUCTURE_FAILURE,
                "persist_failed_after_verify",
                operation=failed_op,
                verification_evidence=evidence,
            ),
        )
    if applied.outcome is TransitionOutcome.REJECTED:
        return (
            "done",
            make_compensation_result(
                CompensationDisposition.REJECTED,
                applied.reason_code,
                operation=applied.operation,
                compensation=applied.compensation,
                transition=applied,
                verification_evidence=evidence,
            ),
        )
    maybe_crash(crash_after, CompensationCrashPoint.AFTER_VERIFY_RESULT_COMMIT)
    assert applied.operation is not None
    assert applied.compensation is not None
    if mapped.kind is CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION:
        assert next_attempt_for_retry is not None
        return (
            "compensate",
            applied.operation,
            applied.compensation,
            next_attempt_for_retry,
        )
    return (
        "done",
        make_compensation_result(
            CompensationDisposition.ACCEPTED,
            "accepted",
            operation=applied.operation,
            compensation=applied.compensation,
            transition=applied,
            verification_evidence=evidence,
        ),
    )


def _call_compensate(
    registry: CapabilityRegistry,
    op: Operation,
    context: object,
    request: object,
) -> CompensationEvidence:
    try:
        adapter = registry.adapter_for(op.intent.effect)
        return adapter.compensate(context, request)  # type: ignore[arg-type]
    except UnsupportedEffectError:
        return CompensationEvidence(
            outcome=EffectOutcome.NOT_APPLIED,
            evidence=None,
            error=NormalizedError(
                contract_version=CONTRACT_VERSION,
                kind=ErrorKind.UNSUPPORTED_CAPABILITY,
                code="ref.compensation.unsupported",
                message="effect does not support compensation",
                retryable_infrastructure=False,
                provider_http_status=None,
                provider_error_code=None,
                retry_after_seconds=None,
                details=json_from_plain({}),
            ),
            external_operation_id=None,
        )
    except ContractValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - defensive adapter boundary
        return CompensationEvidence(
            outcome=EffectOutcome.UNKNOWN,
            evidence=None,
            error=NormalizedError(
                contract_version=CONTRACT_VERSION,
                kind=ErrorKind.TRANSIENT_TRANSPORT,
                code="compensation.adapter_exception",
                message="unclassified compensation adapter exception",
                retryable_infrastructure=True,
                provider_http_status=None,
                provider_error_code=None,
                retry_after_seconds=None,
                details=json_from_plain({"exception_type": type(exc).__name__}),
            ),
            external_operation_id=None,
        )


def _call_verify(
    registry: CapabilityRegistry,
    op: Operation,
    context: object,
    request: VerificationRequest,
    clock: Clock,
) -> VerificationEvidence:
    try:
        adapter = registry.adapter_for(op.intent.effect)
        return adapter.verify(context, request)  # type: ignore[arg-type]
    except (UnsupportedEffectError, ContractValidationError):
        raise
    except Exception as exc:  # noqa: BLE001 - defensive adapter boundary
        from stateback.providers.normalize import evidence_for_unclassified_exception

        outcome, error, ev = evidence_for_unclassified_exception(
            exc=exc, observed_at=clock.now(), provider=op.intent.effect.provider
        )
        return VerificationEvidence(outcome=outcome, evidence=ev, error=error)


def build_compensate_outcome_command(
    *,
    kind: TransitionKind | CompensationProgressKind,
    reason_code: str,
    op: Operation,
    compensation: Compensation,
    completed: CompensationAttempt,
    actor: PrincipalRef,
    correlation_id: str | None,
    occurred_at: UtcTimestamp,
    ids: CompensationIds,
    clock: Clock,
    is_retry: bool = False,
) -> TransitionCommand:
    retry_ids = (
        ids.retry_ids_for.for_attempt(
            compensation.compensation_id, completed.attempt_number
        )
        if is_retry
        else None
    )
    transition_audit_event_id = (
        retry_ids.complete_transition_audit_event_id
        if retry_ids is not None
        else ids.complete_transition_audit_event_id
    )
    compensation_result_audit_event_id = (
        retry_ids.evidence_audit_event_id
        if retry_ids is not None
        else ids.evidence_audit_event_id
    )
    complete_outbox_event_id = (
        retry_ids.complete_outbox_event_id
        if retry_ids is not None
        else ids.complete_outbox_event_id
    )
    verification_id = (
        retry_ids.verification_id if retry_ids is not None else ids.verification_id
    )
    verification_start_audit_event_id = (
        retry_ids.verification_start_audit_event_id
        if retry_ids is not None
        else ids.verification_start_audit_event_id
    )
    verification_outbox_event_id = (
        retry_ids.verification_outbox_event_id
        if retry_ids is not None
        else ids.verification_outbox_event_id
    )
    if kind is TransitionKind.COMPENSATION_APPLIED:
        return CompensationApplied(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_audit_event_id,
            completed_compensation_attempt=completed,
            compensation_result_audit_event_id=compensation_result_audit_event_id,
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_UNKNOWN:
        return CompensationOutcomeUnknown(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_audit_event_id,
            completed_compensation_attempt=completed,
            compensation_result_audit_event_id=compensation_result_audit_event_id,
            outbox_event_id=complete_outbox_event_id,
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_FAILED:
        return CompensationOutcomeFailed(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_audit_event_id,
            completed_compensation_attempt=completed,
            compensation_result_audit_event_id=compensation_result_audit_event_id,
        )
    assert kind is CompensationProgressKind.START_COMPENSATION_VERIFICATION
    request = build_compensation_verification_request(
        operation=op,
        compensation=compensation,
        attempt=completed,
        verification_id=verification_id,
        clock=clock,
    )
    return StartCompensationVerification(
        kind=kind,
        operation_id=op.operation_id,
        expected_operation_version=op.version,
        compensation_id=compensation.compensation_id,
        expected_compensation_version=compensation.version,
        completed_compensation_attempt=completed,
        verification_request=request,
        occurred_at=occurred_at,
        actor=actor,
        correlation_id=correlation_id,
        reason_code=reason_code,
        attempt_audit_event_id=compensation_result_audit_event_id,
        verification_audit_event_id=verification_start_audit_event_id,
        outbox_event_id=verification_outbox_event_id,
    )


def _verify_outcome_command(
    *,
    kind: TransitionKind | CompensationProgressKind,
    reason_code: str,
    op: Operation,
    compensation: Compensation,
    verification_result: VerificationResult,
    completed_for_command: CompensationAttempt | None,
    next_attempt: CompensationAttempt | None,
    actor: PrincipalRef,
    correlation_id: str | None,
    occurred_at: UtcTimestamp,
    ids: CompensationIds,
    idempotency_mode: object,
    current_attempt_number: int,
) -> TransitionCommand:
    transition_event_id, verification_event_id, outcome_outbox_event_id = (
        _verification_write_ids(
            ids=ids,
            compensation_id=compensation.compensation_id,
            attempt_number=current_attempt_number,
            verification_id=verification_result.verification_id,
        )
    )
    if kind is TransitionKind.COMPENSATION_APPLIED:
        assert completed_for_command is not None
        return CompensationApplied(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_event_id,
            completed_compensation_attempt=completed_for_command,
            compensation_result_audit_event_id=verification_event_id,
            verification_result=verification_result,
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_FAILED:
        assert completed_for_command is not None
        return CompensationOutcomeFailed(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_event_id,
            completed_compensation_attempt=completed_for_command,
            compensation_result_audit_event_id=verification_event_id,
            verification_result=verification_result,
        )
    if kind is TransitionKind.COMPENSATION_OUTCOME_UNKNOWN:
        return CompensationOutcomeUnknown(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_event_id,
            completed_compensation_attempt=None,
            compensation_result_audit_event_id=verification_event_id,
            outbox_event_id=outcome_outbox_event_id,
            verification_result=verification_result,
        )
    if kind is TransitionKind.COMPENSATION_ESCALATE:
        return CompensationEscalate(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=COMPENSATION_ACTOR,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=transition_event_id,
            manual_audit_event_id=ids.manual_audit_event_id,
            verification_result=verification_result,
        )
    assert kind is CompensationProgressKind.RETRY_COMPENSATION_AFTER_VERIFICATION
    assert next_attempt is not None
    retry_ids = ids.retry_ids_for.for_attempt(
        compensation.compensation_id, next_attempt.attempt_number
    )
    return RetryCompensationAfterVerification(
        kind=kind,
        operation_id=op.operation_id,
        expected_operation_version=op.version,
        compensation_id=compensation.compensation_id,
        expected_compensation_version=compensation.version,
        verification_result=verification_result,
        attempt=next_attempt,
        idempotency_mode=idempotency_mode,  # type: ignore[arg-type]
        occurred_at=occurred_at,
        actor=actor,
        correlation_id=correlation_id,
        reason_code=reason_code,
        attempt_audit_event_id=retry_ids.attempt_audit_event_id,
        verification_audit_event_id=verification_event_id,
        outbox_event_id=retry_ids.attempt_outbox_event_id,
    )


def _verification_write_ids(
    *,
    ids: CompensationIds,
    compensation_id: OpaqueId,
    attempt_number: int,
    verification_id: OpaqueId,
) -> tuple[OpaqueId, OpaqueId, OpaqueId]:
    if verification_id == ids.verification_id:
        return (
            ids.complete_transition_audit_event_id,
            ids.verification_complete_audit_event_id,
            ids.complete_outbox_event_id,
        )
    if attempt_number >= 2:
        attempt_ids = ids.retry_ids_for.for_attempt(compensation_id, attempt_number)
        if verification_id == attempt_ids.verification_id:
            return (
                attempt_ids.complete_transition_audit_event_id,
                attempt_ids.verification_complete_audit_event_id,
                attempt_ids.complete_outbox_event_id,
            )
    resume_ids = ids.retry_ids_for.for_attempt(compensation_id, attempt_number + 1)
    if verification_id == resume_ids.resume_verification_id:
        return (
            resume_ids.resume_complete_transition_audit_event_id,
            resume_ids.resume_verification_complete_audit_event_id,
            resume_ids.resume_complete_outbox_event_id,
        )
    # Recovery may supply a fresh command ID bundle for a verification request
    # persisted by an earlier command. In that case the current bundle's initial
    # completion IDs are unused and safely identify this write.
    return (
        ids.complete_transition_audit_event_id,
        ids.verification_complete_audit_event_id,
        ids.complete_outbox_event_id,
    )


def _maybe_claim_retry(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    op: Operation,
    compensation: Compensation,
    completed: CompensationAttempt,
    correlation_id: str | None,
    ids: CompensationIds,
    descriptor: EffectDescriptor,
) -> tuple[Operation, Compensation, CompensationAttempt] | CompensationResult | None:
    attempts = list_compensation_attempts(uow_factory, compensation.compensation_id)
    first_started_at = attempts[0].started_at if attempts else completed.started_at
    policy = load_policy(uow_factory, op)
    if policy is None:
        return None
    retry = registry.evaluate_retry_safety(
        effect=op.intent.effect,
        execution_outcome=EffectOutcome.NOT_APPLIED,
        verification_outcome=None,
        now=clock.now(),
        first_attempt_at=first_started_at,
    )
    cap = max_automatic_attempts(policy.obligations)
    if retry.verdict is not RetrySafetyVerdict.SAFE or completed.attempt_number >= cap:
        return None
    next_attempt_number = completed.attempt_number + 1
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
                CompensationFailedRetry(
                    kind=TransitionKind.COMPENSATION_FAILED_RETRY,
                    operation_id=op.operation_id,
                    expected_version=op.version,
                    occurred_at=clock.now(),
                    actor=COMPENSATION_ACTOR,
                    correlation_id=correlation_id,
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
                        kind=CompensationProgressKind.CLAIM_COMPENSATION_RETRY_ATTEMPT,
                        operation_id=retry_result.operation.operation_id,
                        expected_operation_version=retry_result.operation.version,
                        compensation_id=retry_result.compensation.compensation_id,
                        expected_compensation_version=(
                            retry_result.compensation.version
                        ),
                        attempt=next_attempt,
                        occurred_at=clock.now(),
                        actor=COMPENSATION_ACTOR,
                        correlation_id=correlation_id,
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
    assert claim_result.operation is not None
    assert claim_result.compensation is not None
    return (claim_result.operation, claim_result.compensation, next_attempt)
