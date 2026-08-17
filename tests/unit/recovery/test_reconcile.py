from __future__ import annotations

import pytest

from stateback.domain.enums import (
    EffectOutcome,
    ErrorKind,
    ReconciliationAction,
)
from stateback.recovery.reconcile import reconcile
from tests.unit.recovery.fixtures import make_error, make_input, obligations_with

pytestmark = pytest.mark.unit


def test_applied_is_mark_succeeded() -> None:
    decision = reconcile(
        make_input(outcome=EffectOutcome.APPLIED), completed_original_count=1
    )
    assert decision.action is ReconciliationAction.MARK_SUCCEEDED
    assert decision.reason_code == "verification_applied"


def test_not_applied_below_exec_cap_is_retry() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.NOT_APPLIED,
            attempt_number=1,
            obligations=obligations_with(max_automatic_execution_attempts=2),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY
    assert decision.reason_code == "verification_not_applied_retry"


def test_not_applied_at_exec_cap_is_fail() -> None:
    decision = reconcile(
        make_input(outcome=EffectOutcome.NOT_APPLIED, attempt_number=1),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.MARK_FAILED
    assert decision.reason_code == "verification_not_applied_fail"


def test_unknown_transport_is_remain_unknown() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.TRANSIENT_TRANSPORT, code="ref.verify.transport"
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert decision.reason_code == "verification_transport"


def test_unknown_inconclusive_is_remain_unknown() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconclusive"
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert decision.reason_code == "verification_inconclusive"


def test_unknown_inconsistent_is_manual() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconsistent"
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "verification_inconsistent"


def test_unknown_unsupported_is_manual() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.UNSUPPORTED_CAPABILITY,
                code="ref.unsupported.verification",
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "verification_unsupported"


def test_unknown_at_recovery_cap_is_manual() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.PROVIDER_INCONSISTENT, code="ref.verify.inconclusive"
            ),
        ),
        completed_original_count=3,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "recovery_budget_exhausted"


def test_applied_versus_not_applied_execution_is_manual() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.NOT_APPLIED,
            attempt_outcome=EffectOutcome.APPLIED,
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "contradictory_execution_and_verification"


def test_not_applied_versus_applied_execution_is_manual() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.APPLIED,
            attempt_outcome=EffectOutcome.NOT_APPLIED,
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REQUIRE_MANUAL_INTERVENTION
    assert decision.reason_code == "contradictory_execution_and_verification"


def test_unknown_execution_plus_applied_verify_is_succeeded() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.APPLIED,
            attempt_outcome=EffectOutcome.UNKNOWN,
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.MARK_SUCCEEDED
    assert decision.reason_code == "verification_applied"


def test_visibility_window_is_remain_unknown() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.TRANSIENT_TRANSPORT,
                code="ref.verify.visibility_window",
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert decision.reason_code == "verification_visibility_window"


def test_malformed_is_remain_unknown() -> None:
    decision = reconcile(
        make_input(
            outcome=EffectOutcome.UNKNOWN,
            error=make_error(
                kind=ErrorKind.MALFORMED_PROVIDER_RESPONSE,
                code="ref.verify.malformed",
            ),
        ),
        completed_original_count=1,
    )
    assert decision.action is ReconciliationAction.REMAIN_UNKNOWN
    assert decision.reason_code == "verification_malformed"
