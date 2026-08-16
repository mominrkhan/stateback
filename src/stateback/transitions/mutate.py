"""Immutable replace helpers for operation and compensation aggregates."""

from __future__ import annotations

from dataclasses import replace

from stateback.domain.compensation import Compensation
from stateback.domain.enums import CompensationState, OperationState
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.time import UtcTimestamp


class _Unchanged:
    pass


UNCHANGED = _Unchanged()


def replace_operation(
    operation: Operation,
    *,
    state: OperationState,
    version: int,
    updated_at: UtcTimestamp,
    current_policy_decision_id: OpaqueId | None | _Unchanged = UNCHANGED,
    current_approval_id: OpaqueId | None | _Unchanged = UNCHANGED,
    latest_attempt_id: OpaqueId | None | _Unchanged = UNCHANGED,
    latest_verification_id: OpaqueId | None | _Unchanged = UNCHANGED,
    compensation_id: OpaqueId | None | _Unchanged = UNCHANGED,
) -> Operation:
    policy_id = (
        operation.current_policy_decision_id
        if isinstance(current_policy_decision_id, _Unchanged)
        else current_policy_decision_id
    )
    approval_id = (
        operation.current_approval_id
        if isinstance(current_approval_id, _Unchanged)
        else current_approval_id
    )
    attempt_id = (
        operation.latest_attempt_id
        if isinstance(latest_attempt_id, _Unchanged)
        else latest_attempt_id
    )
    verification_id = (
        operation.latest_verification_id
        if isinstance(latest_verification_id, _Unchanged)
        else latest_verification_id
    )
    compensation_pointer = (
        operation.compensation_id
        if isinstance(compensation_id, _Unchanged)
        else compensation_id
    )
    return replace(
        operation,
        state=state,
        version=version,
        updated_at=updated_at,
        current_policy_decision_id=policy_id,
        current_approval_id=approval_id,
        latest_attempt_id=attempt_id,
        latest_verification_id=verification_id,
        compensation_id=compensation_pointer,
    )


def replace_compensation(
    compensation: Compensation,
    *,
    state: CompensationState,
    version: int,
    updated_at: UtcTimestamp,
) -> Compensation:
    return replace(
        compensation,
        state=state,
        version=version,
        updated_at=updated_at,
    )
