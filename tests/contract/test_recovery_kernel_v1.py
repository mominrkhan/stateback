from __future__ import annotations

import pytest

from stateback.domain.enums import OperationState, ReconciliationAction
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.recovery.budget import PHASE6_DEFAULT_RECOVERY_ATTEMPTS
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.kinds import decision_to_kind
from stateback.recovery.results import RecoveryDisposition
from stateback.transitions.kinds import TransitionKind

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_disposition_symbols_are_frozen() -> None:
    assert {member.value for member in RecoveryDisposition} == {
        "ACCEPTED",
        "REJECTED",
        "INFRASTRUCTURE_FAILURE",
    }


def test_crash_points_are_frozen() -> None:
    assert {member.value for member in RecoveryCrashPoint} == {
        "after_start_commit",
        "after_verify_before_result",
        "after_result_commit",
    }


def test_no_probably_applied_symbol_in_recovery() -> None:
    names = {member.name for member in RecoveryDisposition}
    values = {member.value for member in RecoveryDisposition}
    assert "PROBABLY_APPLIED" not in names
    assert "PROBABLY_APPLIED" not in values


def test_reconciliation_actions_round_trip_mapper_for_verifying() -> None:
    expected = {
        ReconciliationAction.MARK_SUCCEEDED: TransitionKind.VERIFICATION_APPLIED,
        ReconciliationAction.MARK_FAILED: TransitionKind.VERIFICATION_NOT_APPLIED_FAIL,
        ReconciliationAction.MAKE_READY_FOR_SAFE_RETRY: (
            TransitionKind.VERIFICATION_NOT_APPLIED_RETRY
        ),
        ReconciliationAction.REMAIN_UNKNOWN: TransitionKind.VERIFICATION_INCONCLUSIVE,
        ReconciliationAction.REQUIRE_MANUAL_INTERVENTION: (
            TransitionKind.VERIFICATION_ESCALATE
        ),
    }
    for action, kind in expected.items():
        mapped = decision_to_kind(
            state=OperationState.VERIFYING,
            decision=ReconciliationDecision(action=action, reason_code="x"),
        )
        assert mapped.kind is kind


def test_phase6_default_recovery_attempts_is_three() -> None:
    assert PHASE6_DEFAULT_RECOVERY_ATTEMPTS == 3
