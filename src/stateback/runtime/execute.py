"""Execute: claim, provider call (no UoW), persist evidence, apply EXECUTION_*."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import (
    EffectDescriptor,
    ExecutionEvidence,
    ProviderExecutionContext,
    ProviderExecutionRequest,
)
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    OperationState,
    VerificationTarget,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest
from stateback.persistence.exceptions import (
    ConcurrencyConflictError,
    NotFoundError,
    PersistenceError,
)
from stateback.persistence.uow import unit_of_work
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.normalize import evidence_for_unclassified_exception
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.attempt import (
    build_completed_attempt,
    build_started_attempt,
    persist_attempt_evidence,
    provider_key_for,
)
from stateback.runtime.clock import Clock
from stateback.runtime.commands import ExecuteCommand
from stateback.runtime.exceptions import StatebackRuntimeError
from stateback.runtime.faults import RuntimeCrashPoint, maybe_crash
from stateback.runtime.ids import ExecuteIds, RecoverIds
from stateback.runtime.outcome import decide_execution_kind
from stateback.runtime.results import (
    RuntimeDisposition,
    RuntimeResult,
    make_result,
)
from stateback.transitions.commands import (
    ClaimExecution,
    ExecutionApplied,
    ExecutionNotAppliedFail,
    ExecutionNotAppliedRetry,
    ExecutionRequireVerification,
    ExecutionUnknown,
    TransitionCommand,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService

_UNSUPPORTED_EXECUTE_STATES = frozenset(
    {
        OperationState.FAILED,
        OperationState.DENIED,
        OperationState.CANCELLED,
        OperationState.UNKNOWN,
        OperationState.VERIFYING,
        OperationState.COMPENSATING,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATED,
        OperationState.COMPENSATION_FAILED,
        OperationState.MANUAL_INTERVENTION,
    }
)


def load_operation(
    uow_factory: sessionmaker[Session], operation_id: OpaqueId
) -> Operation:
    with unit_of_work(uow_factory) as uow:
        op = uow.operations.get(operation_id)
        if op is None:
            raise NotFoundError("operation not found")
        return op


def _latest_attempt(
    uow_factory: sessionmaker[Session], operation: Operation
) -> ExecutionAttempt | None:
    if operation.latest_attempt_id is None:
        return None
    with unit_of_work(uow_factory) as uow:
        return uow.attempts.get(operation.latest_attempt_id)


def _evidence_from_attempt(completed: ExecutionAttempt) -> ExecutionEvidence:
    if completed.outcome is None:
        raise StatebackRuntimeError(
            "illegal_combination",
            "completed attempt is missing outcome",
        )
    return ExecutionEvidence(
        outcome=completed.outcome,
        evidence=completed.evidence,
        error=completed.error,
        external_operation_id=completed.external_operation_id,
        external_resource_ids=completed.external_resource_ids,
    )


def apply_execution_kind(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    operation: Operation,
    completed: ExecutionAttempt,
    actor: PrincipalRef | None,
    correlation_id: str | None,
    evidence_audit_event_id: OpaqueId,
    execution_transition_audit_event_id: OpaqueId,
    execution_outbox_event_id: OpaqueId,
    verification_id: OpaqueId,
    verification_audit_event_id: OpaqueId,
    evidence: ExecutionEvidence,
) -> RuntimeResult:
    if operation.current_policy_decision_id is None:
        return make_result(
            RuntimeDisposition.REJECTED,
            "policy_missing",
            operation=operation,
        )
    descriptor = registry.descriptor(operation.intent.effect)
    with unit_of_work(uow_factory) as uow:
        policy = uow.policy_decisions.get(operation.current_policy_decision_id)
        prior = tuple(uow.attempts.list_for_operation(operation.operation_id))
        if policy is None:
            return make_result(
                RuntimeDisposition.REJECTED,
                "policy_missing",
                operation=operation,
            )
        if completed.outcome is None:
            raise StatebackRuntimeError(
                "illegal_combination",
                "completed attempt is missing outcome",
            )
        first_started_at = prior[0].started_at if prior else completed.started_at
        retry = registry.evaluate_retry_safety(
            effect=operation.intent.effect,
            execution_outcome=completed.outcome,
            verification_outcome=None,
            now=clock.now(),
            first_attempt_at=first_started_at,
        )
        decision = decide_execution_kind(
            outcome=completed.outcome,
            descriptor=descriptor,
            obligations=policy.obligations,
            attempt_number=completed.attempt_number,
            retry_verdict=retry.verdict,
        )
        cmd = _execution_command(
            kind=decision.kind,
            reason_code=decision.reason_code,
            operation=operation,
            completed=completed,
            descriptor=descriptor,
            actor=actor,
            correlation_id=correlation_id,
            occurred_at=clock.now(),
            evidence_audit_event_id=evidence_audit_event_id,
            execution_transition_audit_event_id=execution_transition_audit_event_id,
            execution_outbox_event_id=execution_outbox_event_id,
            verification_id=verification_id,
            verification_audit_event_id=verification_audit_event_id,
        )
        result = transitions.apply(uow, cmd)
    if result.outcome is TransitionOutcome.REJECTED:
        return make_result(
            RuntimeDisposition.REJECTED,
            result.reason_code,
            operation=result.operation,
            transition=result,
            evidence=evidence,
        )
    return make_result(
        RuntimeDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        transition=result,
        evidence=evidence,
    )


def apply_execution_kind_from_ids(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    operation: Operation,
    completed: ExecutionAttempt,
    actor: PrincipalRef | None,
    correlation_id: str | None,
    ids: ExecuteIds | RecoverIds,
    evidence: ExecutionEvidence,
) -> RuntimeResult:
    return apply_execution_kind(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        operation=operation,
        completed=completed,
        actor=actor,
        correlation_id=correlation_id,
        evidence_audit_event_id=ids.evidence_audit_event_id,
        execution_transition_audit_event_id=ids.execution_transition_audit_event_id,
        execution_outbox_event_id=ids.execution_outbox_event_id,
        verification_id=ids.verification_id,
        verification_audit_event_id=ids.verification_audit_event_id,
        evidence=evidence,
    )


def _execution_command(
    *,
    kind: TransitionKind,
    reason_code: str,
    operation: Operation,
    completed: ExecutionAttempt,
    descriptor: EffectDescriptor,
    actor: PrincipalRef | None,
    correlation_id: str | None,
    occurred_at: UtcTimestamp,
    evidence_audit_event_id: OpaqueId,
    execution_transition_audit_event_id: OpaqueId,
    execution_outbox_event_id: OpaqueId,
    verification_id: OpaqueId,
    verification_audit_event_id: OpaqueId,
) -> TransitionCommand:
    if kind is TransitionKind.EXECUTION_APPLIED:
        return ExecutionApplied(
            kind=kind,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=execution_transition_audit_event_id,
            completed_attempt=completed,
            evidence_audit_event_id=evidence_audit_event_id,
        )
    if kind is TransitionKind.EXECUTION_UNKNOWN:
        return ExecutionUnknown(
            kind=kind,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=execution_transition_audit_event_id,
            completed_attempt=completed,
            evidence_audit_event_id=evidence_audit_event_id,
            outbox_event_id=execution_outbox_event_id,
        )
    if kind is TransitionKind.EXECUTION_NOT_APPLIED_RETRY:
        return ExecutionNotAppliedRetry(
            kind=kind,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=execution_transition_audit_event_id,
            completed_attempt=completed,
            evidence_audit_event_id=evidence_audit_event_id,
            idempotency_mode=descriptor.idempotency_mode,
            outbox_event_id=execution_outbox_event_id,
        )
    if kind is TransitionKind.EXECUTION_NOT_APPLIED_FAIL:
        return ExecutionNotAppliedFail(
            kind=kind,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=execution_transition_audit_event_id,
            completed_attempt=completed,
            evidence_audit_event_id=evidence_audit_event_id,
        )
    if kind is TransitionKind.EXECUTION_REQUIRE_VERIFICATION:
        request = VerificationRequest(
            contract_version=CONTRACT_VERSION,
            verification_id=verification_id,
            operation_id=operation.operation_id,
            operation_version=operation.version,
            target=VerificationTarget.ORIGINAL_EFFECT,
            target_attempt_id=completed.attempt_id,
            effect=operation.intent.effect,
            external_operation_id=completed.external_operation_id,
            external_resource_ids=completed.external_resource_ids,
            idempotency_identity=operation.idempotency_identity,
            provider_evidence_refs=(),
            requested_at=occurred_at,
        )
        return ExecutionRequireVerification(
            kind=kind,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=occurred_at,
            actor=actor,
            correlation_id=correlation_id,
            reason_code=reason_code,
            transition_audit_event_id=execution_transition_audit_event_id,
            completed_attempt=completed,
            evidence_audit_event_id=evidence_audit_event_id,
            verification_request=request,
            verification_audit_event_id=verification_audit_event_id,
            outbox_event_id=execution_outbox_event_id,
        )
    raise StatebackRuntimeError(
        "illegal_combination",
        f"unsupported execution kind {kind.value}",
    )


def execute_operation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCommand,
    crash_after: RuntimeCrashPoint | None,
) -> RuntimeResult:
    op = load_operation(uow_factory, command.operation_id)
    return _dispatch(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        command=command,
        crash_after=crash_after,
        op=op,
    )


def _dispatch(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCommand,
    crash_after: RuntimeCrashPoint | None,
    op: Operation,
) -> RuntimeResult:
    if op.state is OperationState.READY:
        return _claim_and_execute(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=op,
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
            return make_result(
                RuntimeDisposition.IN_FLIGHT,
                "in_flight",
                operation=op,
            )
        if attempt.state is AttemptState.COMPLETED:
            return apply_execution_kind_from_ids(
                uow_factory=uow_factory,
                transitions=transitions,
                registry=registry,
                clock=clock,
                operation=op,
                completed=attempt,
                actor=command.actor,
                correlation_id=command.correlation_id,
                ids=command.ids,
                evidence=_evidence_from_attempt(attempt),
            )
        return make_result(
            RuntimeDisposition.REJECTED,
            "unsupported_state",
            operation=op,
        )
    if op.state in {OperationState.PENDING_POLICY, OperationState.AWAITING_APPROVAL}:
        return make_result(
            RuntimeDisposition.REJECTED,
            "not_ready",
            operation=op,
        )
    if op.state is OperationState.SUCCEEDED:
        return make_result(
            RuntimeDisposition.ACCEPTED,
            "already_applied",
            operation=op,
        )
    if op.state in _UNSUPPORTED_EXECUTE_STATES:
        return make_result(
            RuntimeDisposition.REJECTED,
            "unsupported_state",
            operation=op,
        )
    return make_result(
        RuntimeDisposition.REJECTED,
        "unsupported_state",
        operation=op,
    )


def _claim_and_execute(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    clock: Clock,
    command: ExecuteCommand,
    crash_after: RuntimeCrashPoint | None,
    op: Operation,
) -> RuntimeResult:
    ids = command.ids
    descriptor = registry.descriptor(op.intent.effect)
    arguments = op.intent.arguments
    if arguments is None:
        raise StatebackRuntimeError(
            "illegal_combination",
            "INLINE intent is missing arguments at execute",
        )
    request = ProviderExecutionRequest(
        effect=op.intent.effect,
        arguments=arguments,
    )
    adapter = registry.adapter_for(op.intent.effect)
    verification_resource_ids = adapter.verification_resource_ids(request)
    started: ExecutionAttempt | None = None
    claimed: Operation | None = None
    key: str | None = None
    replay = False
    rejected: RuntimeResult | None = None
    try:
        with unit_of_work(uow_factory) as uow:
            prior = tuple(uow.attempts.list_for_operation(op.operation_id))
            key = provider_key_for(
                operation=op,
                descriptor=descriptor,
                prior_attempts=prior,
            )
            started = build_started_attempt(
                operation=op,
                attempt_id=ids.attempt_id,
                attempt_number=len(prior) + 1,
                started_at=clock.now(),
                provider_idempotency_key=key,
                external_resource_ids=verification_resource_ids,
                correlation_id=command.correlation_id,
            )
            result = transitions.apply(
                uow,
                ClaimExecution(
                    kind=TransitionKind.CLAIM_EXECUTION,
                    operation_id=op.operation_id,
                    expected_version=command.expected_version,
                    occurred_at=started.started_at,
                    actor=command.actor,
                    correlation_id=command.correlation_id,
                    reason_code="execution_claimed",
                    transition_audit_event_id=ids.claim_transition_audit_event_id,
                    attempt=started,
                    attempt_audit_event_id=ids.attempt_audit_event_id,
                ),
            )
            if result.outcome is TransitionOutcome.REJECTED:
                rejected = make_result(
                    RuntimeDisposition.REJECTED,
                    result.reason_code,
                    operation=result.operation,
                    transition=result,
                )
            elif result.outcome is TransitionOutcome.ALREADY_APPLIED:
                replay = True
            else:
                claimed = result.operation
    except ConcurrencyConflictError:
        fresh = load_operation(uow_factory, command.operation_id)
        return _dispatch(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=fresh,
        )
    except PersistenceError:
        failed = load_operation(uow_factory, command.operation_id)
        return make_result(
            RuntimeDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed_before_execute",
            operation=failed,
        )
    if rejected is not None:
        return rejected
    if replay:
        fresh = load_operation(uow_factory, command.operation_id)
        return _dispatch(
            uow_factory=uow_factory,
            transitions=transitions,
            registry=registry,
            clock=clock,
            command=command,
            crash_after=crash_after,
            op=fresh,
        )
    if claimed is None or started is None:
        raise StatebackRuntimeError(
            "illegal_combination",
            "claim did not produce a started attempt",
        )
    maybe_crash(crash_after, RuntimeCrashPoint.AFTER_CLAIM_COMMIT)
    context = ProviderExecutionContext(
        operation_id=claimed.operation_id,
        attempt_id=started.attempt_id,
        idempotency_identity=claimed.idempotency_identity,
        provider_idempotency_key=key,
        correlation_id=command.correlation_id,
        deadline=None,
    )
    try:
        evidence = adapter.execute(context, request)
    except (UnsupportedEffectError, ContractValidationError):
        raise
    except Exception as exc:
        outcome, error, ev = evidence_for_unclassified_exception(
            exc=exc,
            observed_at=clock.now(),
            provider=claimed.intent.effect.provider,
        )
        evidence = ExecutionEvidence(
            outcome=outcome,
            evidence=ev,
            error=error,
            external_operation_id=None,
            external_resource_ids=(),
        )
    maybe_crash(crash_after, RuntimeCrashPoint.AFTER_EXECUTE_BEFORE_EVIDENCE)
    completed = build_completed_attempt(
        started=started,
        evidence=evidence,
        completed_at=clock.now(),
    )
    try:
        with unit_of_work(uow_factory) as uow:
            persist_attempt_evidence(uow, completed)
    except PersistenceError:
        failed = load_operation(uow_factory, command.operation_id)
        return make_result(
            RuntimeDisposition.INFRASTRUCTURE_FAILURE,
            "persist_failed_after_execute",
            operation=failed,
            evidence=evidence,
        )
    maybe_crash(crash_after, RuntimeCrashPoint.AFTER_EVIDENCE_COMMIT)
    return apply_execution_kind_from_ids(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        clock=clock,
        operation=claimed,
        completed=completed,
        actor=command.actor,
        correlation_id=command.correlation_id,
        ids=ids,
        evidence=evidence,
    )
