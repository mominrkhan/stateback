"""Compensation evidence helpers. Pure. No I/O."""

from __future__ import annotations

from stateback.domain.capability import CompensationEvidence
from stateback.domain.compensation import CompensationAttempt
from stateback.domain.enums import AttemptState, EffectOutcome
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationResult


def complete_attempt_from_evidence(
    started: CompensationAttempt,
    evidence: CompensationEvidence,
    completed_at: UtcTimestamp,
) -> CompensationAttempt:
    return CompensationAttempt(
        contract_version=started.contract_version,
        compensation_attempt_id=started.compensation_attempt_id,
        compensation_id=started.compensation_id,
        attempt_number=started.attempt_number,
        state=AttemptState.COMPLETED,
        started_at=started.started_at,
        completed_at=completed_at,
        provider_idempotency_key=started.provider_idempotency_key,
        external_operation_id=evidence.external_operation_id,
        outcome=evidence.outcome,
        evidence=evidence.evidence,
        error=evidence.error,
    )


def complete_attempt_from_verification(
    started: CompensationAttempt,
    result: VerificationResult,
    outcome: EffectOutcome,
    completed_at: UtcTimestamp,
) -> CompensationAttempt:
    """Complete a leftover STARTED attempt using verification evidence.

    Used when a compensation attempt never got a durable compensate-side
    completion (crash before evidence commit, or a leftover recovered
    through `COMPENSATION_UNKNOWN`) and verification is now the source of
    truth for what actually happened.
    """
    return CompensationAttempt(
        contract_version=started.contract_version,
        compensation_attempt_id=started.compensation_attempt_id,
        compensation_id=started.compensation_id,
        attempt_number=started.attempt_number,
        state=AttemptState.COMPLETED,
        started_at=started.started_at,
        completed_at=completed_at,
        provider_idempotency_key=started.provider_idempotency_key,
        external_operation_id=started.external_operation_id,
        outcome=outcome,
        evidence=result.evidence,
        error=result.error,
    )
