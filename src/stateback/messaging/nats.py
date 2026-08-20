"""Thin nats.py adapter; canonical decisions remain in relay/worker."""

from __future__ import annotations

import asyncio

from nats.aio.msg import Msg
from nats.js.client import JetStreamContext

from stateback.messaging.codec import encode_quarantine_diagnostic
from stateback.messaging.relay import Publisher
from stateback.messaging.worker import AckDecision, WorkHandler

QUARANTINE_SUBJECT_V1 = "stateback.quarantine.v1"


class JetStreamPublisher:
    def __init__(self, context: JetStreamContext) -> None:
        self._context = context

    async def publish(self, subject: str, payload: bytes) -> None:
        await self._context.publish(subject, payload)


class JetStreamConsumer:
    def __init__(
        self,
        handler: WorkHandler,
        *,
        quarantine_publisher: Publisher,
        quarantine_subject: str = QUARANTINE_SUBJECT_V1,
    ) -> None:
        self._handler = handler
        self._quarantine_publisher = quarantine_publisher
        self._quarantine_subject = quarantine_subject

    async def handle(self, message: Msg) -> AckDecision:
        try:
            delivery_count = message.metadata.num_delivered
        except ValueError:
            delivery_count = 1
        decision = await asyncio.to_thread(
            self._handler.handle,
            message.data,
            delivery_count=delivery_count,
        )
        if decision is AckDecision.ACK:
            await message.ack()
        elif decision is AckDecision.NAK:
            await message.nak()
        else:
            diagnostic = encode_quarantine_diagnostic(
                message.data,
                delivery_count=delivery_count,
            )
            try:
                await self._quarantine_publisher.publish(
                    self._quarantine_subject,
                    diagnostic,
                )
            except Exception:
                # Never terminally acknowledge work unless its diagnostic (and,
                # for valid v1 work, replay payload) is durably accepted.
                await message.nak()
                return AckDecision.NAK
            await message.term()
        return decision
