"""Wrap adapter VerificationEvidence into a durable VerificationResult."""

from __future__ import annotations

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import ProviderExecutionContext, VerificationEvidence
from stateback.domain.enums import CONTRACT_VERSION
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationResult
from stateback.providers.normalize import evidence_for_unclassified_exception


def result_from_evidence(
    *,
    verification_id: OpaqueId,
    evidence: VerificationEvidence,
    completed_at: UtcTimestamp,
) -> VerificationResult:
    return VerificationResult(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        outcome=evidence.outcome,
        evidence=evidence.evidence,
        error=evidence.error,
        completed_at=completed_at,
    )


def context_for_verify(
    *,
    operation: Operation,
    attempt: ExecutionAttempt | None,
    correlation_id: str | None,
) -> ProviderExecutionContext:
    attempt_id = (
        attempt.attempt_id if attempt is not None else operation.latest_attempt_id
    )
    assert attempt_id is not None
    return ProviderExecutionContext(
        operation_id=operation.operation_id,
        attempt_id=attempt_id,
        idempotency_identity=operation.idempotency_identity,
        provider_idempotency_key=(
            None if attempt is None else attempt.provider_idempotency_key
        ),
        correlation_id=correlation_id,
        deadline=None,
    )


def evidence_from_unclassified(
    *,
    exc: Exception,
    observed_at: UtcTimestamp,
    provider: str,
) -> VerificationEvidence:
    outcome, error, ev = evidence_for_unclassified_exception(
        exc=exc, observed_at=observed_at, provider=provider
    )
    return VerificationEvidence(outcome=outcome, evidence=ev, error=error)
