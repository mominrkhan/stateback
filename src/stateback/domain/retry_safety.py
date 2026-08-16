"""Effect-retry safety decisions.

This is not a boolean. Infrastructure retry (`retryable_infrastructure`) is a
different question owned by `NormalizedError`.
"""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.capability import ProviderKeySemantics
from stateback.domain.enums import (
    EffectOutcome,
    IdempotencyMode,
    RetrySafetyBasis,
    RetrySafetyVerdict,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrySafetyDecision:
    verdict: RetrySafetyVerdict
    basis: RetrySafetyBasis | None
    reason_code: str


_INSUFFICIENT = frozenset(
    {
        "timeout_only",
        "worker_died",
        "no_external_id",
        "elapsed_time",
        "logs_show_no_success",
        "model_belief",
        "retryable_infrastructure_flag",
    }
)


def evaluate_effect_retry_safety(
    *,
    execution_outcome: EffectOutcome | None,
    verification_outcome: EffectOutcome | None,
    idempotency_mode: IdempotencyMode,
    insufficient_signal: str | None = None,
    provider_key_semantics: ProviderKeySemantics | None = None,
    replay_window_elapsed: bool = False,
    natural_declaration_tested: bool = False,
) -> RetrySafetyDecision:
    """Classify whether a mutating retry is justified by canonical evidence.

    Policy attempt budgets are not applied here (Phase 9).
    Phase 4 may prove PROVIDER_KEY inside a parsed replay window and NATURAL
    when the declaration has been tested. Omitting the new kwargs preserves
    the Phase 1 defaults: PROVIDER_KEY and untested NATURAL stay
    NEEDS_CAPABILITY_PROOF.
    """

    if insufficient_signal is not None:
        if insufficient_signal not in _INSUFFICIENT:
            return RetrySafetyDecision(
                verdict=RetrySafetyVerdict.UNSAFE,
                basis=None,
                reason_code="unknown_insufficient_signal",
            )
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code=insufficient_signal,
        )

    if execution_outcome is EffectOutcome.APPLIED:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code="already_applied",
        )
    if verification_outcome is EffectOutcome.APPLIED:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code="verification_applied",
        )
    if verification_outcome is EffectOutcome.NOT_APPLIED:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.SAFE,
            basis=RetrySafetyBasis.VERIFIED_NOT_APPLIED,
            reason_code="verification_not_applied",
        )
    if execution_outcome is EffectOutcome.NOT_APPLIED:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.SAFE,
            basis=RetrySafetyBasis.EXECUTION_NOT_APPLIED,
            reason_code="execution_not_applied",
        )

    unresolved = execution_outcome is None or execution_outcome is EffectOutcome.UNKNOWN
    if not unresolved:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code="unhandled_outcome",
        )

    if idempotency_mode is IdempotencyMode.NONE:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code="unknown_without_idempotency",
        )
    if idempotency_mode is IdempotencyMode.NATURAL:
        if not natural_declaration_tested:
            return RetrySafetyDecision(
                verdict=RetrySafetyVerdict.NEEDS_CAPABILITY_PROOF,
                basis=RetrySafetyBasis.NATURAL_IDEMPOTENCY,
                reason_code="natural_idempotency_requires_tested_declaration",
            )
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.SAFE,
            basis=RetrySafetyBasis.NATURAL_IDEMPOTENCY,
            reason_code="natural_idempotency_tested_declaration",
        )
    if provider_key_semantics is None:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.NEEDS_CAPABILITY_PROOF,
            basis=RetrySafetyBasis.PROVIDER_NATIVE_IDEMPOTENCY,
            reason_code="provider_key_requires_adapter_semantics",
        )
    if replay_window_elapsed:
        return RetrySafetyDecision(
            verdict=RetrySafetyVerdict.UNSAFE,
            basis=None,
            reason_code="provider_key_replay_window_elapsed",
        )
    return RetrySafetyDecision(
        verdict=RetrySafetyVerdict.SAFE,
        basis=RetrySafetyBasis.PROVIDER_NATIVE_IDEMPOTENCY,
        reason_code="provider_key_within_replay_window",
    )
