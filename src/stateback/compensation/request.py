"""Request/record builders for compensation. Pure. No I/O."""

from __future__ import annotations

from stateback.compensation.arguments import (
    build_compensation_arguments,
    provider_compensation_key,
)
from stateback.compensation.ids import CompensationIds
from stateback.compensation.intent import compute_compensation_intent_digest
from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import (
    CompensationRequest,
    EffectDescriptor,
    ProviderExecutionContext,
)
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    INITIAL_COMPENSATION_VERSION,
    ArgumentsMode,
    AttemptState,
    CompensationState,
    VerificationTarget,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import compensation_idempotency_identity
from stateback.domain.jsonutil import JsonObject
from stateback.domain.operation import Operation
from stateback.domain.refs import PrincipalRef
from stateback.domain.verification import VerificationRequest
from stateback.runtime.clock import Clock


def build_compensation_record(
    *,
    operation: Operation,
    descriptor: EffectDescriptor,
    ids: CompensationIds,
    actor: PrincipalRef,
    clock: Clock,
    policy_decision_id: OpaqueId | None,
) -> Compensation:
    is_reference = operation.intent.arguments_mode is ArgumentsMode.REFERENCE
    arguments_mode = ArgumentsMode.REFERENCE if is_reference else ArgumentsMode.INLINE
    arguments = None if is_reference else build_compensation_arguments(operation)
    arguments_ref = operation.intent.arguments_ref if is_reference else None
    now = clock.now()
    return Compensation(
        contract_version=CONTRACT_VERSION,
        compensation_id=ids.compensation_id,
        original_operation_id=operation.operation_id,
        kind=descriptor.compensation_kind,
        state=CompensationState.PENDING,
        version=INITIAL_COMPENSATION_VERSION,
        intent_digest=compute_compensation_intent_digest(
            original_operation_id=operation.operation_id,
            kind=descriptor.compensation_kind,
            arguments_mode=arguments_mode,
            arguments=arguments,
            arguments_ref=arguments_ref,
        ),
        arguments_mode=arguments_mode,
        arguments=arguments,
        arguments_ref=arguments_ref,
        idempotency_identity=compensation_idempotency_identity(ids.compensation_id),
        requested_by=actor,
        policy_decision_id=policy_decision_id,
        created_at=now,
        updated_at=now,
    )


def build_started_attempt(
    *,
    compensation_id: OpaqueId,
    attempt_id: OpaqueId,
    attempt_number: int,
    descriptor: EffectDescriptor,
    clock: Clock,
) -> CompensationAttempt:
    return CompensationAttempt(
        contract_version=CONTRACT_VERSION,
        compensation_attempt_id=attempt_id,
        compensation_id=compensation_id,
        attempt_number=attempt_number,
        state=AttemptState.STARTED,
        started_at=clock.now(),
        completed_at=None,
        provider_idempotency_key=provider_compensation_key(
            descriptor=descriptor, compensation_id=compensation_id
        ),
        external_operation_id=None,
        outcome=None,
        evidence=None,
        error=None,
    )


def build_compensation_provider_request(
    *,
    operation: Operation,
    compensation: Compensation,
    attempt: CompensationAttempt,
    original_attempts: tuple[ExecutionAttempt, ...],
) -> CompensationRequest:
    original_evidence = tuple(
        item.evidence for item in original_attempts if item.evidence is not None
    )
    compensation_arguments = (
        compensation.arguments
        if compensation.arguments_mode is ArgumentsMode.INLINE
        else JsonObject(items=(("arguments_ref", compensation.arguments_ref),))
    )
    return CompensationRequest(
        original_operation_id=operation.operation_id,
        compensation_id=compensation.compensation_id,
        compensation_attempt_id=attempt.compensation_attempt_id,
        original_evidence=original_evidence,
        compensation_arguments=compensation_arguments,
        idempotency_identity=compensation.idempotency_identity,
        provider_idempotency_key=attempt.provider_idempotency_key,
    )


def build_compensate_context(
    *,
    operation: Operation,
    attempt: CompensationAttempt,
    compensation: Compensation,
    correlation_id: str | None,
) -> ProviderExecutionContext:
    return ProviderExecutionContext(
        operation_id=operation.operation_id,
        attempt_id=attempt.compensation_attempt_id,
        idempotency_identity=compensation.idempotency_identity,
        provider_idempotency_key=attempt.provider_idempotency_key,
        correlation_id=correlation_id,
        deadline=None,
    )


def build_compensation_verify_context(
    *,
    operation: Operation,
    compensation: Compensation,
    request: VerificationRequest,
    correlation_id: str | None,
) -> ProviderExecutionContext:
    attempt_id = request.target_attempt_id
    assert attempt_id is not None
    return ProviderExecutionContext(
        operation_id=operation.operation_id,
        attempt_id=attempt_id,
        idempotency_identity=compensation.idempotency_identity,
        provider_idempotency_key=None,
        correlation_id=correlation_id,
        deadline=None,
    )


def build_compensation_verification_request(
    *,
    operation: Operation,
    compensation: Compensation,
    attempt: CompensationAttempt,
    verification_id: OpaqueId,
    clock: Clock,
) -> VerificationRequest:
    evidence = attempt.evidence
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        operation_id=operation.operation_id,
        operation_version=operation.version,
        target=VerificationTarget.COMPENSATION,
        target_attempt_id=attempt.compensation_attempt_id,
        effect=operation.intent.effect,
        external_operation_id=attempt.external_operation_id,
        external_resource_ids=(
            evidence.external_resource_ids if evidence is not None else ()
        ),
        idempotency_identity=compensation.idempotency_identity,
        provider_evidence_refs=(),
        requested_at=clock.now(),
    )
