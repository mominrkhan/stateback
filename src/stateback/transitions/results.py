"""Typed outcomes of `TransitionService.apply`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stateback.domain.audit import AuditEvent
from stateback.domain.compensation import Compensation
from stateback.domain.enums import OperationState
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation
from stateback.transitions.kinds import CompensationProgressKind, TransitionKind


class TransitionOutcome(StrEnum):
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionResult:
    outcome: TransitionOutcome
    reason_code: str
    kind: TransitionKind | CompensationProgressKind
    operation: Operation | None
    compensation: Compensation | None
    audit_events: tuple[AuditEvent, ...]
    outbox_event: OutboxEvent | None
    from_state: OperationState | None
    to_state: OperationState | None
    operation_version: int | None
