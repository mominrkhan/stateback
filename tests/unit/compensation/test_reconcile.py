from __future__ import annotations

import pytest

from stateback.compensation.reconcile import reconcile_compensation
from stateback.domain.enums import EffectOutcome, ErrorKind, ReconciliationAction
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from tests.unit.compensation.fixtures import (
    make_compensation_attempt,
    make_error,
    make_verification_result,
    obligations_with,
)

pytestmark = pytest.mark.unit

_DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY]


def test_contradictory_applied_verification_versus_not_applied_attempt() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(outcome=EffectOutcome.APPLIED),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.NOT_APPLIED
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "contradictory_execution_and_verification"


def test_contradictory_not_applied_verification_versus_applied_attempt() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(outcome=EffectOutcome.NOT_APPLIED),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.APPLIED
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "contradictory_execution_and_verification"


def test_inconclusive_remains_unknown() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconclusive"
            ),
        ),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.UNKNOWN
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert decision.reason_code == "verification_inconclusive"


def test_inconsistent_escalates() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconsistent"
            ),
        ),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.UNKNOWN
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "verification_inconsistent"


def test_budget_exhausted_escalates() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconclusive"
            ),
        ),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.UNKNOWN
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(max_automatic_recovery_attempts=2),
        completed_compensation_verify_count=2,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "recovery_budget_exhausted"


def test_not_applied_safe_retry_below_cap() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(outcome=EffectOutcome.NOT_APPLIED),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.UNKNOWN, attempt_number=1
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(max_automatic_execution_attempts=3),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY
    assert decision.reason_code == "verification_not_applied_retry"


def test_not_applied_at_cap_fails() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(outcome=EffectOutcome.NOT_APPLIED),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.UNKNOWN, attempt_number=1
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(max_automatic_execution_attempts=1),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.MARK_FAILED
    assert decision.reason_code == "verification_not_applied_fail"


def test_applied_verification_marks_succeeded() -> None:
    decision = reconcile_compensation(
        verification_result=make_verification_result(outcome=EffectOutcome.APPLIED),
        latest_compensation_attempt=make_compensation_attempt(
            outcome=EffectOutcome.APPLIED
        ),
        descriptor=_DESCRIPTOR,
        obligations=obligations_with(),
        completed_compensation_verify_count=0,
    )
    assert decision.action is ReconciliationAction.MARK_SUCCEEDED
    assert decision.reason_code == "verification_applied"
