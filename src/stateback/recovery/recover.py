"""Recover UNKNOWN / VERIFYING / leftover EXECUTING without a provider mutation."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import EffectDescriptor, VerificationEvidence
from stateback.domain.enums import (
    AttemptState,
    EffectOutcome,
    OperationState,
    RetrySafetyVerdict,
    VerificationMode,
    VerificationTarget,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyDecision
from stateback.domain.reconciliation import ReconciliationInput
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.exceptions import (
    ConcurrencyConflictError,
    NotFoundError,
    PersistenceError,
)
from stateback.persistence.uow import unit_of_work
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.budget import completed_original_verification_count
from stateback.recovery.clock import Clock
from stateback.recovery.commands import RECOVERY_ACTOR, RecoveryCommand
from stateback.recovery.evidence import (
    context_for_verify,
    evidence_from_unclassified,
    result_from_evidence,
)
from stateback.recovery.faults import RecoveryCrashPoint, maybe_crash
from stateback.recovery.ids import RecoveryIds
from stateback.recovery.kinds import decision_to_kind
from stateback.recovery.persist import persist_verification_result
from stateback.recovery.reconcile import reconcile
from stateback.recovery.request import build_original_verification_request
from stateback.recovery.results import (
    RecoveryDisposition,
    RecoveryResult,
    make_recovery_result,
)
from stateback.runtime.commands import RecoverCommand
from stateback.runtime.execute import load_operation
from stateback.runtime.outcome import max_automatic_attempts
from stateback.runtime.recover import recover_operation
from stateback.runtime.results import RuntimeDisposition, RuntimeResult
from stateback.transitions.commands import (
    TransitionCommand,
    UnknownEscalate,
    UnknownSafeRetry,
    UnknownStartVerification,
    VerificationApplied,
    VerificationEscalate,
    VerificationInconclusive,
    VerificationNotAppliedFail,
    VerificationNotAppliedRetry,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService

_ALREADY_APPLIED_STATES = frozenset(
    {
        OperationState.MANUAL_INTERVENTION,
        OperationState.SUCCEEDED,
        OperationState.FAILED,
        OperationState.DENIED,
        OperationState.CANCELLED,
        OperationState.READY,
        OperationState.PENDING_POLICY,
        OperationState.AWAITING_APPROVAL,
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATED,
        OperationState.COMPENSATION_FAILED,
    }
)

_VERIFY_SUPPORTED = frozenset(
    {
        VerificationMode.READ_BACK,
        VerificationMode.OPERATION_LOOKUP,
        VerificationMode.CUSTOM,
    }
)


def recover_unknown_operation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    crash_after: RecoveryCrashPoint | None,
) -> RecoveryResult:
    actor = command.actor if command.actor is not None else RECOVERY_ACTOR
    try:
        op = load_operation(uow_factory, command.operation_id)
    except NotFoundError:
        return make_recovery_result(RecoveryDisposition.REJECTED, "not_found")
    if op.state in _ALREADY_APPLIED_STATES:
        return make_recovery_result(
            RecoveryDisposition.ACCEPTED,
            "already_applied",
            operation=op,
        )
    if op.state is OperationState.EXECUTING:
        return _recover_executing(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            actor=actor,
        )
    if op.state is OperationState.VERIFYING:
        return run_verifying_cycle(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            actor=actor,
        )
    if op.state is OperationState.UNKNOWN:
        return _recover_unknown(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
            actor=actor,
        )
    return make_recovery_result(
        RecoveryDisposition.REJECTED,
        "unsupported_state",
        operation=op,
    )


def run_verifying_cycle(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    crash_after: RecoveryCrashPoint | None,
    op: Operation,
    actor: PrincipalRef,
) -> RecoveryResult:
    if op.state is not OperationState.VERIFYING:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "source_state_mismatch",
            operation=op,
        )
    vid = op.latest_verification_id
    if vid is None:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "verification_missing",
            operation=op,
        )
    loaded = _load_verification(uow_factory, vid)
    if loaded is None:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "verification_missing",
            operation=op,
        )
    request, existing_result = loaded
    if request.target is not VerificationTarget.ORIGINAL_EFFECT:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "verification_outcome_mismatch",
            operation=op,
        )
    if existing_result is None:
        attempt = _attempt_for_request(uow_factory, op, request)
        adapter = registry.adapter_for(op.intent.effect)
        context = context_for_verify(
            operation=op,
            attempt=attempt,
            correlation_id=command.correlation_id,
        )
        verify_request = _request_with_registered_effect(registry, request)
        try:
            evidence = adapter.verify(context, verify_request)
        except (UnsupportedEffectError, ContractValidationError):
            raise
        except Exception as exc:
            evidence = evidence_from_unclassified(
                exc=exc,
                observed_at=clock.now(),
                provider=op.intent.effect.provider,
            )
        maybe_crash(crash_after, RecoveryCrashPoint.AFTER_VERIFY_BEFORE_RESULT)
        result = result_from_evidence(
            verification_id=request.verification_id,
            evidence=evidence,
            completed_at=clock.now(),
        )
        try:
            persist_verification_result(uow_factory, result)
        except PersistenceError as exc:
            if exc.reason_code == "not_found":
                return make_recovery_result(
                    RecoveryDisposition.REJECTED,
                    "verification_missing",
                    operation=op,
                )
            return make_recovery_result(
                RecoveryDisposition.INFRASTRUCTURE_FAILURE,
                "persist_failed_after_verify",
                operation=op,
            )
        maybe_crash(crash_after, RecoveryCrashPoint.AFTER_RESULT_COMMIT)
        existing_result = result
    return _apply_verification_kind(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        op=op,
        actor=actor,
        existing_result=existing_result,
    )


def _recover_executing(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    actor: PrincipalRef,
) -> RecoveryResult:
    runtime_result = recover_operation(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=RecoverCommand(
            operation_id=command.operation_id,
            expected_version=command.expected_version,
            ids=command.ids.execution_recover,
            actor=actor,
            correlation_id=command.correlation_id,
        ),
        crash_after=None,
        policy_engine=None,  # type: ignore[arg-type]
    )
    return _from_runtime_result(runtime_result)


def _recover_unknown(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    crash_after: RecoveryCrashPoint | None,
    op: Operation,
    actor: PrincipalRef,
) -> RecoveryResult:
    descriptor = registry.descriptor(op.intent.effect)
    attempts = _list_attempts(uow_factory, op.operation_id)
    if not attempts:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "attempt_missing",
            operation=op,
        )
    if op.latest_attempt_id is not None:
        latest_row = _get_attempt(uow_factory, op.latest_attempt_id)
        if latest_row is None:
            return make_recovery_result(
                RecoveryDisposition.REJECTED,
                "attempt_missing",
                operation=op,
            )
    policy = _load_policy(uow_factory, op)
    if policy is None:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "policy_missing",
            operation=op,
        )
    if descriptor.verification_mode is VerificationMode.NONE:
        return _unknown_without_verify(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            op=op,
            actor=actor,
            descriptor=descriptor,
            attempts=attempts,
            policy=policy,
        )
    if descriptor.verification_mode not in _VERIFY_SUPPORTED:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "unsupported_state",
            operation=op,
        )
    return _unknown_start_verification(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        crash_after=crash_after,
        op=op,
        actor=actor,
        attempts=attempts,
    )


def _unknown_without_verify(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    op: Operation,
    actor: PrincipalRef,
    descriptor: EffectDescriptor,
    attempts: list[ExecutionAttempt],
    policy: PolicyDecision,
) -> RecoveryResult:
    latest = attempts[-1]
    exec_outcome = (
        latest.outcome
        if latest.state is AttemptState.COMPLETED
        else EffectOutcome.UNKNOWN
    )
    retry = registry.evaluate_retry_safety(
        effect=op.intent.effect,
        execution_outcome=exec_outcome,
        verification_outcome=None,
        now=clock.now(),
        first_attempt_at=attempts[0].started_at,
    )
    ids = command.ids
    if (
        retry.verdict is RetrySafetyVerdict.SAFE
        and latest.attempt_number < max_automatic_attempts(policy.obligations)
    ):
        applied = _apply_transition(
            uow_factory,
            transitions,
            UnknownSafeRetry(
                kind=TransitionKind.UNKNOWN_SAFE_RETRY,
                operation_id=op.operation_id,
                expected_version=op.version,
                occurred_at=clock.now(),
                actor=actor,
                correlation_id=command.correlation_id,
                reason_code=retry.reason_code,
                transition_audit_event_id=ids.complete_transition_audit_event_id,
                idempotency_mode=descriptor.idempotency_mode,
                execution_outcome=exec_outcome,
                verification_outcome=None,
                outbox_event_id=ids.retry_outbox_event_id,
                insufficient_signal=None,
            ),
        )
        return _from_apply(applied, operation=op)
    reason_code = (
        "execution_attempt_budget_exhausted"
        if retry.verdict is RetrySafetyVerdict.SAFE
        else "unknown_without_verification"
    )
    applied = _apply_transition(
        uow_factory,
        transitions,
        UnknownEscalate(
            kind=TransitionKind.UNKNOWN_ESCALATE,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=clock.now(),
            actor=actor,
            correlation_id=command.correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            manual_audit_event_id=ids.manual_audit_event_id,
        ),
    )
    return _from_apply(applied, operation=op)


def _unknown_start_verification(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    crash_after: RecoveryCrashPoint | None,
    op: Operation,
    actor: PrincipalRef,
    attempts: list[ExecutionAttempt],
) -> RecoveryResult:
    ids = command.ids
    latest = attempts[-1] if attempts else None
    request = build_original_verification_request(
        operation=op,
        attempt=latest,
        verification_id=ids.verification_id,
        requested_at=clock.now(),
    )
    applied = _apply_transition(
        uow_factory,
        transitions,
        UnknownStartVerification(
            kind=TransitionKind.UNKNOWN_START_VERIFICATION,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=clock.now(),
            actor=actor,
            correlation_id=command.correlation_id,
            reason_code="unknown_start_verification",
            transition_audit_event_id=ids.start_transition_audit_event_id,
            verification_request=request,
            verification_audit_event_id=ids.verification_start_audit_event_id,
            outbox_event_id=ids.start_outbox_event_id,
        ),
    )
    mapped = _from_apply(applied, operation=op)
    if mapped.disposition is not RecoveryDisposition.ACCEPTED:
        return mapped
    if mapped.reason_code == "already_applied":
        reloaded = load_operation(uow_factory, command.operation_id)
        return run_verifying_cycle(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=reloaded,
            actor=actor,
        )
    assert mapped.operation is not None
    maybe_crash(crash_after, RecoveryCrashPoint.AFTER_START_COMMIT)
    return run_verifying_cycle(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        crash_after=crash_after,
        op=mapped.operation,
        actor=actor,
    )


def _apply_verification_kind(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: RecoveryCommand,
    op: Operation,
    actor: PrincipalRef,
    existing_result: VerificationResult,
) -> RecoveryResult:
    attempts = _list_attempts(uow_factory, op.operation_id)
    policy = _load_policy(uow_factory, op)
    if policy is None:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "policy_missing",
            operation=op,
        )
    descriptor = registry.descriptor(op.intent.effect)
    rows = _list_verifications(uow_factory, op.operation_id)
    count = completed_original_verification_count(rows)
    decision = reconcile(
        ReconciliationInput(
            operation=op,
            attempts=tuple(attempts),
            verification_result=existing_result,
            provider_descriptor=descriptor,
            policy_obligations=policy.obligations,
        ),
        completed_original_count=count,
    )
    mapped = decision_to_kind(state=OperationState.VERIFYING, decision=decision)
    ids = command.ids
    cmd = _verification_command(
        kind=mapped.kind,
        op=op,
        actor=actor,
        correlation_id=command.correlation_id,
        occurred_at=clock.now(),
        reason_code=decision.reason_code,
        ids=ids,
        existing_result=existing_result,
        descriptor=descriptor,
    )
    applied = _apply_transition(uow_factory, transitions, cmd)
    if isinstance(applied, RecoveryResult):
        return applied
    if applied.outcome is TransitionOutcome.REJECTED:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            applied.reason_code,
            operation=applied.operation,
            transition=applied,
            verification_evidence=_evidence_of(existing_result),
            decision=decision,
        )
    if applied.outcome is TransitionOutcome.ALREADY_APPLIED:
        return make_recovery_result(
            RecoveryDisposition.ACCEPTED,
            "already_applied",
            operation=applied.operation,
            transition=applied,
            verification_evidence=_evidence_of(existing_result),
            decision=decision,
        )
    return make_recovery_result(
        RecoveryDisposition.ACCEPTED,
        "accepted",
        operation=applied.operation,
        transition=applied,
        verification_evidence=_evidence_of(existing_result),
        decision=decision,
    )


def _verification_command(
    *,
    kind: TransitionKind,
    op: Operation,
    actor: PrincipalRef,
    correlation_id: str | None,
    occurred_at: UtcTimestamp,
    reason_code: str,
    ids: RecoveryIds,
    existing_result: VerificationResult,
    descriptor: EffectDescriptor,
) -> TransitionCommand:
    if kind is TransitionKind.VERIFICATION_APPLIED:
        return VerificationApplied(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            verification_result=existing_result,
            verification_audit_event_id=ids.verification_complete_audit_event_id,
        )
    if kind is TransitionKind.VERIFICATION_NOT_APPLIED_FAIL:
        return VerificationNotAppliedFail(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            verification_result=existing_result,
            verification_audit_event_id=ids.verification_complete_audit_event_id,
        )
    if kind is TransitionKind.VERIFICATION_NOT_APPLIED_RETRY:
        return VerificationNotAppliedRetry(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            verification_result=existing_result,
            verification_audit_event_id=ids.verification_complete_audit_event_id,
            idempotency_mode=descriptor.idempotency_mode,
            outbox_event_id=ids.retry_outbox_event_id,
            insufficient_signal=None,
        )
    if kind is TransitionKind.VERIFICATION_INCONCLUSIVE:
        return VerificationInconclusive(
            kind=kind,
            operation_id=op.operation_id,
            expected_version=op.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=ids.complete_transition_audit_event_id,
            verification_result=existing_result,
            verification_audit_event_id=ids.verification_complete_audit_event_id,
        )
    return VerificationEscalate(
        kind=kind,
        operation_id=op.operation_id,
        expected_version=op.version,
        occurred_at=occurred_at,
        actor=actor,
        correlation_id=correlation_id,
        reason_code=reason_code,
        transition_audit_event_id=ids.complete_transition_audit_event_id,
        verification_result=existing_result,
        manual_audit_event_id=ids.manual_audit_event_id,
    )


def _apply_transition(
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    command: TransitionCommand,
) -> TransitionResult | RecoveryResult:
    try:
        with unit_of_work(uow_factory) as uow:
            return transitions.apply(uow, command)
    except NotFoundError:
        return make_recovery_result(RecoveryDisposition.REJECTED, "not_found")
    except ConcurrencyConflictError:
        return make_recovery_result(
            RecoveryDisposition.INFRASTRUCTURE_FAILURE,
            "stale_version",
        )
    except PersistenceError:
        return make_recovery_result(
            RecoveryDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed",
        )


def _from_apply(
    applied: TransitionResult | RecoveryResult,
    *,
    operation: Operation,
) -> RecoveryResult:
    if isinstance(applied, RecoveryResult):
        if applied.operation is None:
            return make_recovery_result(
                applied.disposition,
                applied.reason_code,
                operation=operation,
            )
        return applied
    if applied.outcome is TransitionOutcome.REJECTED:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            applied.reason_code,
            operation=applied.operation,
            transition=applied,
        )
    if applied.outcome is TransitionOutcome.ALREADY_APPLIED:
        return make_recovery_result(
            RecoveryDisposition.ACCEPTED,
            "already_applied",
            operation=applied.operation,
            transition=applied,
        )
    return make_recovery_result(
        RecoveryDisposition.ACCEPTED,
        "accepted",
        operation=applied.operation,
        transition=applied,
    )


def _from_runtime_result(runtime: RuntimeResult) -> RecoveryResult:
    if runtime.disposition is RuntimeDisposition.IN_FLIGHT:
        return make_recovery_result(
            RecoveryDisposition.REJECTED,
            "in_flight_not_scanner_safe",
            operation=runtime.operation,
            transition=runtime.transition,
        )
    if runtime.disposition is RuntimeDisposition.ACCEPTED:
        disposition = RecoveryDisposition.ACCEPTED
    elif runtime.disposition is RuntimeDisposition.REJECTED:
        disposition = RecoveryDisposition.REJECTED
    else:
        disposition = RecoveryDisposition.INFRASTRUCTURE_FAILURE
    return make_recovery_result(
        disposition,
        runtime.reason_code,
        operation=runtime.operation,
        transition=runtime.transition,
    )


def _evidence_of(result: VerificationResult) -> VerificationEvidence:
    return VerificationEvidence(
        outcome=result.outcome,
        evidence=result.evidence,
        error=result.error,
    )


def _request_with_registered_effect(
    registry: CapabilityRegistry, request: VerificationRequest
) -> VerificationRequest:
    canonical = registry.descriptor(request.effect).effect
    if canonical is request.effect:
        return request
    return replace(request, effect=canonical)


def _list_attempts(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[ExecutionAttempt]:
    with unit_of_work(uow_factory) as uow:
        return uow.attempts.list_for_operation(operation_id)


def _get_attempt(
    uow_factory: sessionmaker[Session], attempt_id: OpaqueId
) -> ExecutionAttempt | None:
    with unit_of_work(uow_factory) as uow:
        return uow.attempts.get(attempt_id)


def _load_policy(
    uow_factory: sessionmaker[Session], op: Operation
) -> PolicyDecision | None:
    if op.current_policy_decision_id is None:
        return None
    with unit_of_work(uow_factory) as uow:
        return uow.policy_decisions.get(op.current_policy_decision_id)


def _load_verification(
    uow_factory: sessionmaker[Session], verification_id: OpaqueId
) -> tuple[VerificationRequest, VerificationResult | None] | None:
    with unit_of_work(uow_factory) as uow:
        return uow.verifications.get(verification_id)


def _list_verifications(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[tuple[VerificationRequest, VerificationResult | None]]:
    with unit_of_work(uow_factory) as uow:
        return uow.verifications.list_for_operation(operation_id)


def _attempt_for_request(
    uow_factory: sessionmaker[Session],
    op: Operation,
    request: VerificationRequest,
) -> ExecutionAttempt | None:
    if request.target_attempt_id is not None:
        loaded = _get_attempt(uow_factory, request.target_attempt_id)
        if loaded is not None:
            return loaded
    if op.latest_attempt_id is not None:
        return _get_attempt(uow_factory, op.latest_attempt_id)
    return None
