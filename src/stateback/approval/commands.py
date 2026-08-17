"""Approval decision commands and caller-supplied durable IDs."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import ApprovalState
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalDecisionIds:
    transition_audit_event_id: OpaqueId
    approval_audit_event_id: OpaqueId
    outbox_event_id: OpaqueId


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalDecisionCommand:
    operation_id: OpaqueId
    approval_id: OpaqueId
    expected_version: int
    decision: ApprovalState
    actor: PrincipalRef
    reason: str | None
    correlation_id: str | None
    ids: ApprovalDecisionIds

    def __post_init__(self) -> None:
        if self.decision not in {ApprovalState.APPROVED, ApprovalState.REJECTED}:
            raise ValueError("decision must be APPROVED or REJECTED")
        if self.expected_version < 1:
            raise ValueError("expected_version must be >= 1")


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalExpiryCommand:
    operation_id: OpaqueId
    approval_id: OpaqueId
    expected_version: int
    transition_audit_event_id: OpaqueId
    correlation_id: str | None

    def __post_init__(self) -> None:
        if self.expected_version < 1:
            raise ValueError("expected_version must be >= 1")
