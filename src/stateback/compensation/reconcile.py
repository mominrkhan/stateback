"""Pure compensation-verification reconciliation. No provider I/O, no persistence."""

from __future__ import annotations

from stateback.domain.capability import EffectDescriptor
from stateback.domain.compensation import CompensationAttempt
from stateback.domain.enums import (
    AttemptState,
    EffectOutcome,
    ErrorKind,
    IdempotencyMode,
    ReconciliationAction,
    RetrySafetyVerdict,
    VerificationTarget,
)
from stateback.domain.policy import PolicyObligations
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.domain.retry_safety import evaluate_effect_retry_safety
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.recovery.budget import max_automatic_recovery_attempts
from stateback.runtime.outcome import max_automatic_attempts


def completed_compensation_verification_count(
    rows: list[tuple[VerificationRequest, VerificationResult | None]],
) -> int:
    return sum(
        1
        for request, result in rows
        if request.target is VerificationTarget.COMPENSATION and result is not None
    )


def reconcile_compensation(
    *,
    verification_result: VerificationResult,
    latest_compensation_attempt: CompensationAttempt | None,
    descriptor: EffectDescriptor,
    obligations: PolicyObligations,
    completed_compensation_verify_count: int,
) -> ReconciliationDecision:
    v = verification_result
    latest = latest_compensation_attempt
    if latest is None:
        latest_outcome = None
        attempt_number = 0
    elif latest.state is AttemptState.COMPLETED:
        latest_outcome = latest.outcome
        attempt_number = latest.attempt_number
    else:
        latest_outcome = EffectOutcome.UNKNOWN
        attempt_number = latest.attempt_number
    cap_exec = max_automatic_attempts(obligations)
    cap_rec = max_automatic_recovery_attempts(obligations)
    code = v.error.code if v.error is not None else ""
    kind = v.error.kind if v.error is not None else None

    if v.outcome is EffectOutcome.APPLIED:
        if latest_outcome is EffectOutcome.NOT_APPLIED:
            return ReconciliationDecision(
                action=ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
                reason_code="contradictory_execution_and_verification",
            )
        return ReconciliationDecision(
            action=ReconciliationAction.MARK_SUCCEEDED,
            reason_code="verification_applied",
        )
    if v.outcome is EffectOutcome.NOT_APPLIED:
        if latest_outcome is EffectOutcome.APPLIED:
            return ReconciliationDecision(
                action=ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
                reason_code="contradictory_execution_and_verification",
            )
        safety = evaluate_effect_retry_safety(
            execution_outcome=None,
            verification_outcome=EffectOutcome.NOT_APPLIED,
            idempotency_mode=descriptor.idempotency_mode,
            provider_key_semantics=descriptor.provider_key_semantics,
            replay_window_elapsed=False,
            natural_declaration_tested=descriptor.idempotency_mode
            is IdempotencyMode.NATURAL,
        )
        if safety.verdict is RetrySafetyVerdict.SAFE and attempt_number < cap_exec:
            return ReconciliationDecision(
                action=ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY,
                reason_code="verification_not_applied_retry",
            )
        return ReconciliationDecision(
            action=ReconciliationAction.MARK_FAILED,
            reason_code="verification_not_applied_fail",
        )

    if kind is ErrorKind.UNSUPPORTED_CAPABILITY:
        return ReconciliationDecision(
            action=ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
            reason_code="verification_unsupported",
        )
    if code == "ref.verify.inconsistent":
        return ReconciliationDecision(
            action=ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
            reason_code="verification_inconsistent",
        )
    if completed_compensation_verify_count >= cap_rec:
        return ReconciliationDecision(
            action=ReconciliationAction.REQUIRE_MANUAL_INTERVENTION,
            reason_code="recovery_budget_exhausted",
        )
    if code == "ref.verify.transport":
        reason = "verification_transport"
    elif code == "ref.verify.visibility_window":
        reason = "verification_visibility_window"
    elif code == "ref.verify.malformed":
        reason = "verification_malformed"
    elif code == "ref.verify.inconclusive":
        reason = "verification_inconclusive"
    elif kind is ErrorKind.MALFORMED_PROVIDER_RESPONSE:
        reason = "verification_malformed"
    elif kind is ErrorKind.TRANSIENT_TRANSPORT:
        reason = "verification_transport"
    else:
        reason = "verification_inconclusive"
    return ReconciliationDecision(
        action=ReconciliationAction.REMAIN_UNKNOWN,
        reason_code=reason,
    )
