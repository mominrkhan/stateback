"""Transactional-outbox relay.

The PostgreSQL row lock is held until JetStream acknowledges publication and
the row is marked PUBLISHED. A crash in that interval can publish twice; it
cannot lose the durable need to publish.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.audit import AuditEvent
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AuditEventType,
    OperationState,
    OutboxState,
    PrincipalType,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.messaging import OutboxEvent, WorkMessageV1
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.messaging.codec import encode_work_message
from stateback.persistence.uow import unit_of_work
from stateback.runtime.clock import Clock
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService

WORK_SUBJECT_V1 = "stateback.work.v1"
RECOVERY_REPUBLISHED_REASON = "messaging.recovery_republished"
RECOVERY_EXHAUSTED_REASON = "messaging.recovery_exhausted"
RECOVERY_ACTOR = PrincipalRef(
    type=PrincipalType.SERVICE,
    id="stateback.outbox_recovery",
    display_name="StatebackOutboxRecovery",
)

_COMMAND_STATES: dict[WorkCommand, frozenset[OperationState]] = {
    WorkCommand.EXECUTE: frozenset({OperationState.READY, OperationState.EXECUTING}),
    WorkCommand.VERIFY: frozenset(
        {
            OperationState.EXECUTING,
            OperationState.UNKNOWN,
            OperationState.VERIFYING,
            OperationState.COMPENSATING,
            OperationState.COMPENSATION_UNKNOWN,
        }
    ),
    WorkCommand.COMPENSATE: frozenset(
        {
            OperationState.COMPENSATING,
            OperationState.COMPENSATION_UNKNOWN,
            OperationState.COMPENSATION_FAILED,
        }
    ),
}


class Publisher(Protocol):
    async def publish(self, subject: str, payload: bytes) -> None: ...


class MessageIdFactory(Protocol):
    def for_outbox(self, event_id: OpaqueId) -> OpaqueId: ...


class OutboxRelay:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        publisher: Publisher,
        clock: Clock,
        message_ids: MessageIdFactory,
        subject: str = WORK_SUBJECT_V1,
    ) -> None:
        self._factory = session_factory
        self._publisher = publisher
        self._clock = clock
        self._message_ids = message_ids
        self._subject = subject

    async def publish_pending(self, *, limit: int) -> int:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        published = 0
        for _ in range(limit):
            if not await self._publish_one():
                break
            published += 1
        return published

    def recover_stranded(
        self, *, limit: int, after_seconds: int, max_recoveries: int = 3
    ) -> int:
        """Schedule fresh outbox history for old published work still required."""

        if limit < 1:
            raise ValueError("limit must be >= 1")
        if after_seconds < 1:
            raise ValueError("after_seconds must be >= 1")
        if max_recoveries < 1:
            raise ValueError("max_recoveries must be >= 1")
        now = self._clock.now()
        cutoff = UtcTimestamp(value=now.value - timedelta(seconds=after_seconds))
        with unit_of_work(self._factory) as uow:
            candidate_ids = uow.outbox_events.list_stranded_candidate_ids(cutoff, limit)
        recovered = 0
        for candidate_id in candidate_ids:
            with unit_of_work(self._factory) as uow:
                source = uow.outbox_events.get(candidate_id)
                if source is None:
                    continue
                operation = uow.operations.get_for_update(source.aggregate_id)
                if operation is None:
                    continue
                latest = uow.outbox_events.latest_for_operation(operation.operation_id)
                if (
                    latest is None
                    or latest.event_id != source.event_id
                    or source.state is not OutboxState.PUBLISHED
                    or source.published_at is None
                    or source.published_at.value > cutoff.value
                    or operation.state not in _COMMAND_STATES[source.command]
                ):
                    continue
                recovery_count = uow.audit_events.count_reason_for_command(
                    operation.operation_id,
                    RECOVERY_REPUBLISHED_REASON,
                    source.command,
                    operation.version,
                )
                if recovery_count >= max_recoveries:
                    exhausted_count = uow.audit_events.count_reason_for_command(
                        operation.operation_id,
                        RECOVERY_EXHAUSTED_REASON,
                        source.command,
                        operation.version,
                    )
                    if exhausted_count == 0:
                        result = TransitionService().escalate_messaging_recovery(
                            uow,
                            operation_id=operation.operation_id,
                            expected_version=operation.version,
                            occurred_at=now,
                            actor=RECOVERY_ACTOR,
                            correlation_id=source.correlation_id,
                            reason_code=RECOVERY_EXHAUSTED_REASON,
                            transition_audit_event_id=_recovery_id(
                                source.event_id, "exhausted"
                            ),
                            command=source.command,
                            max_recoveries=max_recoveries,
                        )
                        if result.outcome is not TransitionOutcome.APPLIED:
                            raise RuntimeError("messaging recovery escalation rejected")
                    continue
                replay_id = _recovery_id(source.event_id, "outbox")
                audit_id = _recovery_id(source.event_id, "audit")
                uow.outbox_events.insert(
                    OutboxEvent(
                        contract_version=CONTRACT_VERSION,
                        event_id=replay_id,
                        state=OutboxState.PENDING,
                        aggregate_type="operation",
                        aggregate_id=operation.operation_id,
                        operation_version=operation.version,
                        command=source.command,
                        created_at=now,
                        published_at=None,
                        correlation_id=source.correlation_id,
                    )
                )
                uow.audit_events.append(
                    AuditEvent(
                        contract_version=CONTRACT_VERSION,
                        audit_event_id=audit_id,
                        operation_id=operation.operation_id,
                        sequence=uow.audit_events.next_sequence(operation.operation_id),
                        event_type=AuditEventType.OUTBOX_DIAGNOSTIC,
                        from_state=None,
                        to_state=None,
                        operation_version=operation.version,
                        actor=RECOVERY_ACTOR,
                        reason_code=RECOVERY_REPUBLISHED_REASON,
                        data=json_from_plain(
                            {
                                "source_outbox_event_id": source.event_id.value,
                                "recovery_outbox_event_id": replay_id.value,
                                "command": source.command.value,
                            }
                        ),
                        correlation_id=source.correlation_id,
                        created_at=now,
                    )
                )
                recovered += 1
        return recovered

    async def _publish_one(self) -> bool:
        with unit_of_work(self._factory) as uow:
            pending = uow.outbox_events.list_pending_for_claim(1)
            if not pending:
                return False
            event = pending[0]
            message = _message_for(event, self._message_ids.for_outbox(event.event_id))
            await self._publisher.publish(self._subject, encode_work_message(message))
            uow.outbox_events.mark_published(event.event_id, self._clock.now())
        return True


def _message_for(event: OutboxEvent, message_id: OpaqueId) -> WorkMessageV1:
    return WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=message_id,
        outbox_event_id=event.event_id,
        operation_id=event.aggregate_id,
        expected_operation_version=event.operation_version,
        command=event.command,
        correlation_id=event.correlation_id,
        created_at=event.created_at,
    )


def _recovery_id(source_event_id: OpaqueId, purpose: str) -> OpaqueId:
    return OpaqueId(
        value=str(
            uuid5(
                NAMESPACE_URL,
                f"stateback:outbox-recovery:{source_event_id.value}:{purpose}",
            )
        )
    )
