from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, RetrySafetyVerdict
from stateback.domain.policy import PolicyObligations
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.outcome import decide_execution_kind
from stateback.runtime.results import RuntimeDisposition
from stateback.transitions.kinds import TransitionKind

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_disposition_symbols_are_frozen() -> None:
    assert {member.value for member in RuntimeDisposition} == {
        "ACCEPTED",
        "REJECTED",
        "IN_FLIGHT",
        "INFRASTRUCTURE_FAILURE",
    }


def test_crash_points_are_frozen() -> None:
    assert {member.value for member in RuntimeCrashPoint} == {
        "after_intent_commit",
        "after_policy_commit",
        "after_claim_commit",
        "after_execute_before_evidence",
        "after_evidence_commit",
    }


def test_no_probably_applied_symbol_in_runtime() -> None:
    names = {member.name for member in RuntimeDisposition}
    values = {member.value for member in RuntimeDisposition}
    assert "PROBABLY_APPLIED" not in names
    assert "PROBABLY_APPLIED" not in values


def test_unknown_distinct_from_failed_in_mapper() -> None:
    obligations = PolicyObligations(
        require_verification=False,
        max_automatic_execution_attempts=1,
        max_automatic_recovery_attempts=None,
        automatic_compensation_allowed=False,
        operator_reason_required=False,
        approval_expires_at=None,
    )
    unknown = decide_execution_kind(
        outcome=EffectOutcome.UNKNOWN,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=obligations,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.SAFE,
    )
    failed = decide_execution_kind(
        outcome=EffectOutcome.NOT_APPLIED,
        descriptor=REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY],
        obligations=obligations,
        attempt_number=1,
        retry_verdict=RetrySafetyVerdict.SAFE,
    )
    assert unknown.kind is TransitionKind.EXECUTION_UNKNOWN
    assert failed.kind is TransitionKind.EXECUTION_NOT_APPLIED_FAIL
    assert unknown.kind.value != failed.kind.value
