"""Recovery-attempt budget. Execution retry cap remains Phase 5 max_automatic_attempts."""

from __future__ import annotations

from stateback.domain.enums import VerificationTarget
from stateback.domain.policy import PolicyObligations
from stateback.domain.verification import VerificationRequest, VerificationResult

PHASE6_DEFAULT_RECOVERY_ATTEMPTS = 3


def max_automatic_recovery_attempts(obligations: PolicyObligations) -> int:
    value = obligations.max_automatic_recovery_attempts
    if value is None or value < 1:
        return PHASE6_DEFAULT_RECOVERY_ATTEMPTS
    return value


def completed_original_verification_count(
    rows: list[tuple[VerificationRequest, VerificationResult | None]],
) -> int:
    return sum(
        1
        for request, result in rows
        if request.target is VerificationTarget.ORIGINAL_EFFECT and result is not None
    )
