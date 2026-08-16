from __future__ import annotations

import pytest

from stateback.domain.enums import (
    AuditEventType,
    EffectOutcome,
    OperationState,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_operation_states_are_canonical_symbols() -> None:
    assert OperationState.UNKNOWN.value == "UNKNOWN"
    assert OperationState.FAILED.value == "FAILED"


def test_effect_outcome_has_no_probably_applied() -> None:
    values = {member.value for member in EffectOutcome}
    assert values == {"APPLIED", "NOT_APPLIED", "UNKNOWN"}
    assert "PROBABLY_APPLIED" not in values


def test_audit_event_types_are_versioned_identifiers() -> None:
    values = tuple(member.value for member in AuditEventType)
    assert values == (
        "operation.created.v1",
        "policy.evaluated.v1",
        "approval.requested.v1",
        "approval.decided.v1",
        "operation.transitioned.v1",
        "execution.attempt_started.v1",
        "execution.evidence_recorded.v1",
        "verification.started.v1",
        "verification.completed.v1",
        "reconciliation.decided.v1",
        "compensation.requested.v1",
        "compensation.attempted.v1",
        "compensation.result.v1",
        "operator.action.v1",
        "outbox.diagnostic.v1",
        "manual_intervention.reason.v1",
        "security.control_decision.v1",
    )
    assert all(value.endswith(".v1") for value in values)
    assert "UPDATED" not in values
    assert "UPDATED" not in {member.name for member in AuditEventType}
