"""Transactional-outbox relay.

The PostgreSQL row lock is held until JetStream acknowledges publication and
the row is marked PUBLISHED. A crash in that interval can publish twice; it
cannot lose the durable need to publish.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import CONTRACT_VERSION
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import OutboxEvent, WorkMessageV1
from stateback.messaging.codec import encode_work_message
from stateback.persistence.uow import unit_of_work
from stateback.runtime.clock import Clock

WORK_SUBJECT_V1 = "stateback.work.v1"


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
