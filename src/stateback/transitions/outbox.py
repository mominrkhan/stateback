"""Outbox mapping for kinds that require async work."""

from __future__ import annotations

from stateback.domain.enums import (
    CONTRACT_VERSION,
    OutboxState,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import OutboxEvent
from stateback.domain.time import UtcTimestamp
from stateback.transitions.kinds import TransitionKind

OUTBOX_COMMAND_FOR_KIND: dict[TransitionKind, WorkCommand] = {
    TransitionKind.POLICY_ALLOW: WorkCommand.EXECUTE,
    TransitionKind.APPROVAL_GRANT: WorkCommand.EXECUTE,
    TransitionKind.EXECUTION_REQUIRE_VERIFICATION: WorkCommand.VERIFY,
    TransitionKind.EXECUTION_NOT_APPLIED_RETRY: WorkCommand.EXECUTE,
    TransitionKind.EXECUTION_UNKNOWN: WorkCommand.VERIFY,
    TransitionKind.VERIFICATION_NOT_APPLIED_RETRY: WorkCommand.EXECUTE,
    TransitionKind.UNKNOWN_START_VERIFICATION: WorkCommand.VERIFY,
    TransitionKind.UNKNOWN_SAFE_RETRY: WorkCommand.EXECUTE,
    TransitionKind.SUCCEEDED_START_COMPENSATION: WorkCommand.COMPENSATE,
    TransitionKind.FAILED_START_COMPENSATION: WorkCommand.COMPENSATE,
    TransitionKind.MANUAL_START_VERIFICATION: WorkCommand.VERIFY,
    TransitionKind.MANUAL_START_COMPENSATION: WorkCommand.COMPENSATE,
    TransitionKind.MANUAL_SAFE_RETRY: WorkCommand.EXECUTE,
    TransitionKind.COMPENSATION_OUTCOME_UNKNOWN: WorkCommand.COMPENSATE,
    TransitionKind.COMPENSATION_UNKNOWN_RETRY: WorkCommand.COMPENSATE,
    TransitionKind.COMPENSATION_FAILED_RETRY: WorkCommand.COMPENSATE,
}


def build_outbox_event(
    *,
    event_id: OpaqueId,
    operation_id: OpaqueId,
    operation_version: int,
    command: WorkCommand,
    created_at: UtcTimestamp,
    correlation_id: str | None,
) -> OutboxEvent:
    return OutboxEvent(
        contract_version=CONTRACT_VERSION,
        event_id=event_id,
        state=OutboxState.PENDING,
        aggregate_type="operation",
        aggregate_id=operation_id,
        operation_version=operation_version,
        command=command,
        created_at=created_at,
        published_at=None,
        correlation_id=correlation_id,
    )
