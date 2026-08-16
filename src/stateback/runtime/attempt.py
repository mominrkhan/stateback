"""Attempt construction and evidence persist (FM-009 path; no lifecycle apply)."""

from __future__ import annotations

import dataclasses

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import EffectDescriptor, ExecutionEvidence
from stateback.domain.enums import CONTRACT_VERSION, AttemptState, IdempotencyMode
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.time import UtcTimestamp
from stateback.persistence.uow import UnitOfWork


def provider_key_for(
    *,
    operation: Operation,
    descriptor: EffectDescriptor,
    prior_attempts: tuple[ExecutionAttempt, ...],
) -> str | None:
    existing = next(
        (
            attempt.provider_idempotency_key
            for attempt in prior_attempts
            if attempt.provider_idempotency_key
        ),
        None,
    )
    if existing is not None:
        return existing
    if descriptor.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
        return operation.idempotency_identity
    return None


def build_started_attempt(
    *,
    operation: Operation,
    attempt_id: OpaqueId,
    attempt_number: int,
    started_at: UtcTimestamp,
    provider_idempotency_key: str | None,
    correlation_id: str | None,
) -> ExecutionAttempt:
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=attempt_id,
        operation_id=operation.operation_id,
        attempt_number=attempt_number,
        state=AttemptState.STARTED,
        started_at=started_at,
        completed_at=None,
        provider_idempotency_key=provider_idempotency_key,
        external_operation_id=None,
        external_resource_ids=(),
        outcome=None,
        evidence=None,
        error=None,
        correlation_id=correlation_id,
    )


def build_completed_attempt(
    *,
    started: ExecutionAttempt,
    evidence: ExecutionEvidence,
    completed_at: UtcTimestamp,
) -> ExecutionAttempt:
    return dataclasses.replace(
        started,
        state=AttemptState.COMPLETED,
        completed_at=completed_at,
        outcome=evidence.outcome,
        evidence=evidence.evidence,
        error=evidence.error,
        external_operation_id=evidence.external_operation_id,
        external_resource_ids=evidence.external_resource_ids,
    )


def persist_attempt_evidence(uow: UnitOfWork, completed: ExecutionAttempt) -> None:
    uow.attempts.complete(completed)
