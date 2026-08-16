"""Submit: validate, persist intent, evaluate policy. Never calls execute."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.capability import EffectDescriptor, ProviderExecutionRequest
from stateback.domain.enums import (
    CONTRACT_VERSION,
    INITIAL_OPERATION_VERSION,
    ApprovalState,
    ArgumentsMode,
    Mutability,
    OperationState,
    PolicyVerdict,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.intent import IntentEnvelope, operation_idempotency_identity
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision
from stateback.persistence.exceptions import DuplicateKeyError
from stateback.persistence.uow import unit_of_work
from stateback.policy.evaluation import PolicyEvaluation
from stateback.policy.inputs import PolicyInputs
from stateback.policy.protocol import PolicyEngine
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime.clock import Clock
from stateback.runtime.commands import SubmitCommand
from stateback.runtime.faults import RuntimeCrashPoint, maybe_crash
from stateback.runtime.results import (
    RuntimeDisposition,
    RuntimeResult,
    make_result,
)
from stateback.transitions.commands import (
    CreateOperation,
    PolicyAllow,
    PolicyDeny,
    PolicyRequireApproval,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome, TransitionResult
from stateback.transitions.service import TransitionService


def _policy_inputs(
    operation: Operation,
    descriptor: EffectDescriptor,
    deployment_environment: str,
) -> PolicyInputs:
    return PolicyInputs(
        operation_id=operation.operation_id,
        operation_version=operation.version,
        intent_digest=operation.intent.intent_digest,
        requester=operation.intent.requester,
        effect=operation.intent.effect,
        risk_level=descriptor.risk_level,
        mutability=descriptor.mutability,
        idempotency_mode=descriptor.idempotency_mode,
        verification_mode=descriptor.verification_mode,
        compensation_kind=descriptor.compensation_kind,
        metadata=operation.intent.metadata,
        deployment_environment=deployment_environment,
    )


def _apply_policy(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    policy_engine: PolicyEngine,
    clock: Clock,
    command: SubmitCommand,
    operation: Operation,
    crash_after: RuntimeCrashPoint | None,
) -> RuntimeResult:
    if operation.state is not OperationState.PENDING_POLICY:
        return make_result(
            RuntimeDisposition.ACCEPTED,
            "already_applied",
            operation=operation,
        )
    descriptor = registry.descriptor(operation.intent.effect)
    inputs = _policy_inputs(operation, descriptor, command.deployment_environment)
    try:
        evaluation = policy_engine.evaluate(inputs)
    except Exception:
        return make_result(
            RuntimeDisposition.INFRASTRUCTURE_FAILURE,
            "policy_engine_failed",
            operation=operation,
        )
    return _persist_policy(
        uow_factory=uow_factory,
        transitions=transitions,
        clock=clock,
        command=command,
        operation=operation,
        evaluation=evaluation,
        crash_after=crash_after,
    )


def _persist_policy(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    clock: Clock,
    command: SubmitCommand,
    operation: Operation,
    evaluation: PolicyEvaluation,
    crash_after: RuntimeCrashPoint | None,
) -> RuntimeResult:
    now = clock.now()
    ids = command.ids
    decision = PolicyDecision(
        contract_version=CONTRACT_VERSION,
        policy_decision_id=ids.policy_decision_id,
        operation_id=operation.operation_id,
        operation_version=operation.version,
        intent_digest=operation.intent.intent_digest,
        verdict=evaluation.verdict,
        reason_codes=evaluation.reason_codes,
        explanation=evaluation.explanation,
        obligations=evaluation.obligations,
        policy_revision=evaluation.policy_revision,
        evaluated_at=now,
    )
    cmd: PolicyAllow | PolicyDeny | PolicyRequireApproval
    if evaluation.verdict is PolicyVerdict.ALLOW:
        cmd = PolicyAllow(
            kind=TransitionKind.POLICY_ALLOW,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=now,
            actor=command.requester,
            correlation_id=command.correlation_id,
            reason_code="policy_allow",
            transition_audit_event_id=ids.policy_transition_audit_event_id,
            policy_decision=decision,
            policy_audit_event_id=ids.policy_audit_event_id,
            outbox_event_id=ids.allow_outbox_event_id,
        )
    elif evaluation.verdict is PolicyVerdict.DENY:
        cmd = PolicyDeny(
            kind=TransitionKind.POLICY_DENY,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=now,
            actor=command.requester,
            correlation_id=command.correlation_id,
            reason_code="policy_deny",
            transition_audit_event_id=ids.policy_transition_audit_event_id,
            policy_decision=decision,
            policy_audit_event_id=ids.policy_audit_event_id,
        )
    else:
        approval = Approval(
            contract_version=CONTRACT_VERSION,
            approval_id=ids.approval_id,
            operation_id=operation.operation_id,
            operation_version=next_version(operation.version),
            intent_digest=operation.intent.intent_digest,
            policy_decision_id=decision.policy_decision_id,
            state=ApprovalState.PENDING,
            requested_at=now,
            expires_at=evaluation.obligations.approval_expires_at,
            decided_at=None,
            decided_by=None,
            reason=None,
        )
        cmd = PolicyRequireApproval(
            kind=TransitionKind.POLICY_REQUIRE_APPROVAL,
            operation_id=operation.operation_id,
            expected_version=operation.version,
            occurred_at=now,
            actor=command.requester,
            correlation_id=command.correlation_id,
            reason_code="policy_require_approval",
            transition_audit_event_id=ids.policy_transition_audit_event_id,
            policy_decision=decision,
            approval=approval,
            policy_audit_event_id=ids.policy_audit_event_id,
            approval_audit_event_id=ids.approval_audit_event_id,
        )
    with unit_of_work(uow_factory) as uow:
        result = transitions.apply(uow, cmd)
    if result.outcome is TransitionOutcome.REJECTED:
        return make_result(
            RuntimeDisposition.REJECTED,
            result.reason_code,
            operation=result.operation,
            transition=result,
        )
    maybe_crash(crash_after, RuntimeCrashPoint.AFTER_POLICY_COMMIT)
    return make_result(
        RuntimeDisposition.ACCEPTED,
        "accepted",
        operation=result.operation,
        transition=result,
    )


def submit_operation(
    *,
    uow_factory: sessionmaker[Session],
    transitions: TransitionService,
    registry: CapabilityRegistry,
    policy_engine: PolicyEngine,
    clock: Clock,
    command: SubmitCommand,
    crash_after: RuntimeCrashPoint | None,
) -> RuntimeResult:
    try:
        descriptor = registry.descriptor(command.effect)
    except UnsupportedEffectError:
        return make_result(RuntimeDisposition.REJECTED, "unregistered_effect")
    if descriptor.mutability is Mutability.READ_ONLY:
        return make_result(
            RuntimeDisposition.REJECTED,
            "read_only_effect_not_consequential",
        )
    try:
        intent = IntentEnvelope.from_parts(
            effect=command.effect,
            arguments_mode=ArgumentsMode.INLINE,
            arguments=command.arguments,
            arguments_ref=None,
            requester=command.requester,
            requested_at=clock.now(),
            metadata=command.metadata,
        )
    except ContractValidationError as exc:
        return make_result(RuntimeDisposition.REJECTED, exc.reason_code)
    request = ProviderExecutionRequest(
        effect=command.effect,
        arguments=command.arguments,
    )
    adapter = registry.adapter_for(command.effect)
    validation = adapter.validate_execution(request)
    if not validation.accepted:
        return make_result(
            RuntimeDisposition.REJECTED,
            "validation_rejected",
            validation_error=validation.error,
        )
    operation = Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=command.ids.operation_id,
        state=OperationState.PENDING_POLICY,
        version=INITIAL_OPERATION_VERSION,
        intent=intent,
        risk_level=descriptor.risk_level,
        idempotency_identity=operation_idempotency_identity(command.ids.operation_id),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=None,
        latest_verification_id=None,
        compensation_id=None,
        created_at=intent.requested_at,
        updated_at=intent.requested_at,
    )
    try:
        with unit_of_work(uow_factory) as uow:
            create_result = transitions.apply(
                uow,
                CreateOperation(
                    kind=TransitionKind.CREATE_OPERATION,
                    operation=operation,
                    occurred_at=intent.requested_at,
                    actor=command.requester,
                    correlation_id=command.correlation_id,
                    reason_code="operation_submitted",
                    created_audit_event_id=command.ids.created_audit_event_id,
                ),
            )
    except DuplicateKeyError:
        with unit_of_work(uow_factory) as uow:
            existing = uow.operations.get(command.ids.operation_id)
            if existing is None:
                existing = uow.operations.get_by_idempotency_identity(
                    operation.idempotency_identity
                )
        if existing is None:
            raise
        if existing.intent.intent_digest != intent.intent_digest:
            return make_result(
                RuntimeDisposition.REJECTED,
                "intent_conflict",
                operation=existing,
            )
        create_result = TransitionResult(
            outcome=TransitionOutcome.ALREADY_APPLIED,
            reason_code="already_applied",
            kind=TransitionKind.CREATE_OPERATION,
            operation=existing,
            compensation=None,
            audit_events=(),
            outbox_event=None,
            from_state=None,
            to_state=OperationState.PENDING_POLICY,
            operation_version=existing.version,
        )
    if create_result.outcome is TransitionOutcome.REJECTED:
        reused = create_result.operation
        if (
            create_result.reason_code == "operation_id_reused"
            and reused is not None
            and reused.intent.intent_digest == intent.intent_digest
        ):
            loaded = reused
        else:
            return make_result(
                RuntimeDisposition.REJECTED,
                create_result.reason_code,
                operation=create_result.operation,
                transition=create_result,
            )
    elif create_result.outcome is TransitionOutcome.ALREADY_APPLIED:
        existing = create_result.operation
        if existing is None:
            return make_result(
                RuntimeDisposition.REJECTED,
                "transition_rejected",
                transition=create_result,
            )
        if existing.intent.intent_digest != intent.intent_digest:
            return make_result(
                RuntimeDisposition.REJECTED,
                "intent_conflict",
                operation=existing,
                transition=create_result,
            )
        loaded = existing
    else:
        created = create_result.operation
        if created is None:
            return make_result(
                RuntimeDisposition.REJECTED,
                "transition_rejected",
                transition=create_result,
            )
        loaded = created
    maybe_crash(crash_after, RuntimeCrashPoint.AFTER_INTENT_COMMIT)
    return _apply_policy(
        uow_factory=uow_factory,
        transitions=transitions,
        registry=registry,
        policy_engine=policy_engine,
        clock=clock,
        command=command,
        operation=loaded,
        crash_after=crash_after,
    )
