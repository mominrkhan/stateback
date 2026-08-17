"""Approval-service result types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stateback.domain.operation import Operation
from stateback.domain.policy import Approval
from stateback.transitions.results import TransitionResult


class ApprovalDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalResult:
    disposition: ApprovalDisposition
    reason_code: str
    operation: Operation | None
    approval: Approval | None
    transition: TransitionResult | None
