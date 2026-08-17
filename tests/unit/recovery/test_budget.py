from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, VerificationTarget
from stateback.recovery.budget import (
    PHASE6_DEFAULT_RECOVERY_ATTEMPTS,
    completed_original_verification_count,
    max_automatic_recovery_attempts,
)
from tests.unit.recovery.fixtures import (
    make_verification_request,
    make_verification_result,
    obligations_with,
)

pytestmark = pytest.mark.unit


def test_none_or_less_than_one_is_three() -> None:
    assert max_automatic_recovery_attempts(obligations_with()) == 3
    assert (
        max_automatic_recovery_attempts(
            obligations_with(max_automatic_recovery_attempts=0)
        )
        == PHASE6_DEFAULT_RECOVERY_ATTEMPTS
    )
    assert (
        max_automatic_recovery_attempts(
            obligations_with(max_automatic_recovery_attempts=-1)
        )
        == 3
    )


def test_explicit_positive_cap_is_honored() -> None:
    assert (
        max_automatic_recovery_attempts(
            obligations_with(max_automatic_recovery_attempts=7)
        )
        == 7
    )


def test_completed_count_ignores_incomplete_and_compensation_target() -> None:
    result = make_verification_result(outcome=EffectOutcome.UNKNOWN)
    rows = [
        (make_verification_request(), result),
        (make_verification_request(), None),
        (
            make_verification_request(target=VerificationTarget.COMPENSATION),
            result,
        ),
    ]
    assert completed_original_verification_count(rows) == 1
