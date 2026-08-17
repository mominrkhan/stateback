from __future__ import annotations

import pytest

from stateback.compensation import (
    CompensationCrashPoint,
    CompensationDisposition,
    CompensationRetryIdFactory,
    CompensationRetryIds,
    CompensationService,
)
from stateback.domain.enums import CompensationKind, CompensationState
from stateback.transitions.kinds import CompensationProgressKind

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_compensation_service_imported() -> None:
    assert CompensationService is not None


def test_retry_id_contract_is_exported() -> None:
    assert CompensationRetryIds is not None
    assert CompensationRetryIdFactory is not None


def test_compensation_disposition_symbols_are_frozen() -> None:
    assert {member.value for member in CompensationDisposition} == {
        "ACCEPTED",
        "REJECTED",
        "IN_FLIGHT",
        "INFRASTRUCTURE_FAILURE",
        "NOT_ELIGIBLE",
    }


def test_compensation_crash_points_are_frozen() -> None:
    assert {member.value for member in CompensationCrashPoint} == {
        "after_start_commit",
        "after_claim_commit",
        "after_compensate_before_evidence",
        "after_evidence_commit",
        "after_verify_start_commit",
        "after_verify_before_result",
        "after_verify_result_commit",
    }


def test_no_probably_applied_symbol_in_compensation() -> None:
    names = {member.name for member in CompensationDisposition}
    values = {member.value for member in CompensationDisposition}
    assert "PROBABLY_APPLIED" not in names
    assert "PROBABLY_APPLIED" not in values


def test_compensation_kind_symbols_match_domain() -> None:
    assert {member.value for member in CompensationKind} == {
        "NONE",
        "EXACT",
        "APPROXIMATE",
        "MITIGATING",
    }


def test_compensation_state_symbols_match_domain() -> None:
    assert {member.value for member in CompensationState} == {
        "PENDING",
        "EXECUTING",
        "VERIFYING",
        "UNKNOWN",
        "SUCCEEDED",
        "FAILED",
    }


def test_progress_kind_names_match_spec() -> None:
    assert {member.value for member in CompensationProgressKind} == {
        "CLAIM_COMPENSATION_EXECUTION",
        "START_COMPENSATION_VERIFICATION",
        "CLAIM_COMPENSATION_RETRY_ATTEMPT",
        "RETRY_COMPENSATION_AFTER_VERIFICATION",
    }
