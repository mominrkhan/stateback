from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import nats
import pytest
from nats.aio.msg import Msg
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.service import CompensationService
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AuditEventType,
    EffectOutcome,
    IdempotencyMode,
    OperationState,
    OutboxState,
    PrincipalType,
    WorkCommand,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_to_plain
from stateback.domain.messaging import WorkMessageV1
from stateback.domain.refs import PrincipalRef
from stateback.messaging.codec import encode_work_message
from stateback.messaging.nats import JetStreamConsumer, JetStreamPublisher
from stateback.messaging.relay import OutboxRelay
from stateback.messaging.worker import AckDecision, WorkHandler
from stateback.persistence.engine import create_engine_from_url, session_factory
from stateback.persistence.uow import unit_of_work
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SimulatedCrash
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.service import SynchronousRuntime
from stateback.transitions.commands import ManualSafeRetry
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService
from tests.integration.runtime.conftest import (
    load_operation,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, submit_ids

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.nats,
    pytest.mark.benchmark_correctness,
]


class FixedMessageIds:
    def for_outbox(self, event_id: OpaqueId) -> OpaqueId:
        del event_id
        return OpaqueId(value="00000000-0000-4000-8000-00000000f001")


class RecordingPublisher:
    def __init__(self, *, fail_after_publish: bool = False) -> None:
        self.messages: list[tuple[str, bytes]] = []
        self.fail_after_publish = fail_after_publish

    async def publish(self, subject: str, payload: bytes) -> None:
        self.messages.append((subject, payload))
        if self.fail_after_publish:
            raise ConnectionError("simulated publish acknowledgement loss")


class FakeMetadata:
    num_delivered = 2


class FakeJetStreamMessage:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.metadata = FakeMetadata()
        self.acked = False
        self.naked = False
        self.termed = False

    async def ack(self) -> None:
        self.acked = True

    async def nak(self) -> None:
        self.naked = True

    async def term(self) -> None:
        self.termed = True


def services(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> tuple[RecoveryService, CompensationService]:
    return (
        RecoveryService(
            session_factory=uow_factory,
            registry=registry,
            clock=clock,
        ),
        CompensationService(
            session_factory=uow_factory,
            registry=registry,
            clock=clock,
        ),
    )


def test_relay_marks_published_only_after_publisher_ack(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    submitted = runtime.submit(make_submit(seq))
    assert submitted.operation is not None
    publisher = RecordingPublisher()
    relay = OutboxRelay(
        session_factory=uow_factory,
        publisher=publisher,
        clock=clock,
        message_ids=FixedMessageIds(),
    )

    assert asyncio.run(relay.publish_pending(limit=1)) == 1
    assert len(publisher.messages) == 1
    with unit_of_work(uow_factory) as uow:
        event = uow.outbox_events.get(
            WorkMessageV1.from_wire(
                json.loads(publisher.messages[0][1])
            ).outbox_event_id
        )
        assert event is not None
        assert event.state is OutboxState.PUBLISHED
        assert event.published_at == clock.now()


def test_publish_ack_loss_leaves_pending_and_republishes(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    submitted = runtime.submit(make_submit(seq))
    assert submitted.operation is not None
    failing = RecordingPublisher(fail_after_publish=True)
    relay = OutboxRelay(
        session_factory=uow_factory,
        publisher=failing,
        clock=clock,
        message_ids=FixedMessageIds(),
    )
    with pytest.raises(ConnectionError):
        asyncio.run(relay.publish_pending(limit=1))

    publisher = RecordingPublisher()
    retry = OutboxRelay(
        session_factory=uow_factory,
        publisher=publisher,
        clock=clock,
        message_ids=FixedMessageIds(),
    )
    assert asyncio.run(retry.publish_pending(limit=1)) == 1
    assert len(failing.messages) == 1
    assert len(publisher.messages) == 1
    assert failing.messages[0][1] == publisher.messages[0][1]


def test_published_message_loss_creates_new_auditable_outbox_history(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    submitted = runtime.submit(make_submit(seq))
    assert submitted.operation is not None
    publisher = RecordingPublisher()
    relay = OutboxRelay(
        session_factory=uow_factory,
        publisher=publisher,
        clock=clock,
        message_ids=FixedMessageIds(),
    )
    assert asyncio.run(relay.publish_pending(limit=1)) == 1
    original = WorkMessageV1.from_wire(json.loads(publisher.messages[0][1]))

    clock.advance(301)
    assert relay.recover_stranded(limit=10, after_seconds=300) == 1
    assert relay.recover_stranded(limit=10, after_seconds=300) == 0
    with unit_of_work(uow_factory) as uow:
        original_event = uow.outbox_events.get(original.outbox_event_id)
        latest = uow.outbox_events.latest_for_operation(original.operation_id)
        audit = uow.audit_events.list_for_operation(original.operation_id)
    assert original_event is not None
    assert original_event.state is OutboxState.PUBLISHED
    assert latest is not None
    assert latest.event_id != original_event.event_id
    assert latest.state is OutboxState.PENDING
    assert latest.operation_version == submitted.operation.version
    assert audit[-1].reason_code == "messaging.recovery_republished"

    assert asyncio.run(relay.publish_pending(limit=1)) == 1
    replay = WorkMessageV1.from_wire(json.loads(publisher.messages[-1][1]))
    assert replay.outbox_event_id == latest.event_id
    assert replay.operation_id == original.operation_id

    for _ in range(2):
        clock.advance(301)
        assert relay.recover_stranded(limit=10, after_seconds=300) == 1
        assert asyncio.run(relay.publish_pending(limit=1)) == 1
    clock.advance(301)
    with ThreadPoolExecutor(max_workers=2) as pool:
        exhausted_results = list(
            pool.map(
                lambda _: relay.recover_stranded(limit=10, after_seconds=300),
                range(2),
            )
        )
    assert exhausted_results == [0, 0]
    clock.advance(301)
    assert relay.recover_stranded(limit=10, after_seconds=300) == 0
    with unit_of_work(uow_factory) as uow:
        audit = uow.audit_events.list_for_operation(original.operation_id)
        exhausted_operation = uow.operations.get(original.operation_id)
        manual_operations = uow.operations.list_by_state(
            OperationState.MANUAL_INTERVENTION
        )
    assert exhausted_operation is not None
    assert exhausted_operation.state is OperationState.MANUAL_INTERVENTION
    assert exhausted_operation.version == submitted.operation.version + 1
    assert [operation.operation_id for operation in manual_operations] == [
        original.operation_id
    ]
    assert (
        sum(event.reason_code == "messaging.recovery_republished" for event in audit)
        == 3
    )
    assert (
        sum(event.reason_code == "messaging.recovery_exhausted" for event in audit) == 1
    )
    assert json_to_plain(audit[-1].data) == {
        "command": "EXECUTE",
        "max_recoveries": 3,
        "operator_intervention_required": True,
    }
    assert audit[-1].event_type is AuditEventType.OPERATION_TRANSITIONED
    assert audit[-1].from_state is OperationState.READY
    assert audit[-1].to_state is OperationState.MANUAL_INTERVENTION
    assert audit[-1].operation_version == submitted.operation.version + 1

    with unit_of_work(uow_factory) as uow:
        resumed = TransitionService().apply(
            uow,
            ManualSafeRetry(
                kind=TransitionKind.MANUAL_SAFE_RETRY,
                operation_id=original.operation_id,
                expected_version=exhausted_operation.version,
                occurred_at=clock.now(),
                actor=PrincipalRef(
                    type=PrincipalType.OPERATOR,
                    id="recovery-operator",
                    display_name=None,
                ),
                correlation_id=None,
                reason_code="operator_safe_retry",
                transition_audit_event_id=seq.next(),
                idempotency_mode=IdempotencyMode.NONE,
                execution_outcome=EffectOutcome.NOT_APPLIED,
                verification_outcome=None,
                operator_audit_event_id=seq.next(),
                outbox_event_id=seq.next(),
            ),
        )
    assert resumed.outcome is TransitionOutcome.APPLIED
    assert resumed.operation is not None
    assert resumed.operation.state is OperationState.READY
    assert asyncio.run(relay.publish_pending(limit=1)) == 1

    for _ in range(3):
        clock.advance(301)
        assert relay.recover_stranded(limit=10, after_seconds=300) == 1
        assert asyncio.run(relay.publish_pending(limit=1)) == 1
    clock.advance(301)
    assert relay.recover_stranded(limit=10, after_seconds=300) == 0
    with unit_of_work(uow_factory) as uow:
        resumed_exhausted = uow.operations.get(original.operation_id)
        resumed_audit = uow.audit_events.list_for_operation(original.operation_id)
    assert resumed_exhausted is not None
    assert resumed_exhausted.state is OperationState.MANUAL_INTERVENTION
    assert (
        sum(
            event.reason_code == "messaging.recovery_exhausted"
            for event in resumed_audit
        )
        == 2
    )


def test_concurrent_recovery_scans_schedule_one_republish(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    submitted = runtime.submit(make_submit(seq))
    assert submitted.operation is not None
    relay = OutboxRelay(
        session_factory=uow_factory,
        publisher=RecordingPublisher(),
        clock=clock,
        message_ids=FixedMessageIds(),
    )
    assert asyncio.run(relay.publish_pending(limit=1)) == 1
    clock.advance(301)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: relay.recover_stranded(limit=10, after_seconds=300),
                range(2),
            )
        )
    assert sorted(results) == [0, 1]

    with unit_of_work(uow_factory) as uow:
        audit = uow.audit_events.list_for_operation(submitted.operation.operation_id)
    assert (
        sum(event.reason_code == "messaging.recovery_republished" for event in audit)
        == 1
    )


def test_worker_duplicate_delivery_executes_provider_once(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    with unit_of_work(uow_factory) as uow:
        outbox = uow.outbox_events.list_pending_for_claim(1)[0]
    payload = encode_work_message(
        WorkMessageV1(
            contract_version=CONTRACT_VERSION,
            message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f002"),
            outbox_event_id=outbox.event_id,
            operation_id=outbox.aggregate_id,
            expected_operation_version=outbox.operation_version,
            command=outbox.command,
            correlation_id=outbox.correlation_id,
            created_at=outbox.created_at,
        )
    )

    assert handler.handle(payload, delivery_count=1) is AckDecision.ACK
    assert handler.handle(payload, delivery_count=2) is AckDecision.ACK
    assert (
        load_operation(uow_factory, ids.operation_id).state is OperationState.SUCCEEDED
    )
    assert len(store.all_resources()) == 1


def test_concurrent_workers_execute_provider_once(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    with unit_of_work(uow_factory) as uow:
        outbox = uow.outbox_events.list_pending_for_claim(1)[0]
    payload = encode_work_message(
        WorkMessageV1(
            contract_version=CONTRACT_VERSION,
            message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f006"),
            outbox_event_id=outbox.event_id,
            operation_id=outbox.aggregate_id,
            expected_operation_version=outbox.operation_version,
            command=outbox.command,
            correlation_id=outbox.correlation_id,
            created_at=outbox.created_at,
        )
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = tuple(
            pool.map(
                lambda delivery: handler.handle(payload, delivery_count=delivery),
                (1, 1),
            )
        )

    assert decisions == (AckDecision.ACK, AckDecision.ACK)
    assert (
        load_operation(uow_factory, ids.operation_id).state is OperationState.SUCCEEDED
    )
    assert len(store.all_resources()) == 1


def test_redelivery_after_provider_effect_crash_routes_to_unknown_not_reexecution(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    crashing_runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,
        crash_after=RuntimeCrashPoint.AFTER_EXECUTE_BEFORE_EVIDENCE,
    )
    ids = submit_ids(seq)
    submitted = crashing_runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    recovery, compensation = services(uow_factory, registry, clock)
    crashing_handler = WorkHandler(
        session_factory=uow_factory,
        runtime=crashing_runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    with unit_of_work(uow_factory) as uow:
        outbox = uow.outbox_events.list_pending_for_claim(1)[0]
    payload = encode_work_message(
        WorkMessageV1(
            contract_version=CONTRACT_VERSION,
            message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f007"),
            outbox_event_id=outbox.event_id,
            operation_id=outbox.aggregate_id,
            expected_operation_version=outbox.operation_version,
            command=outbox.command,
            correlation_id=outbox.correlation_id,
            created_at=outbox.created_at,
        )
    )
    with pytest.raises(SimulatedCrash):
        crashing_handler.handle(payload, delivery_count=1)
    assert len(store.all_resources()) == 1

    restarted = rebuild_runtime(uow_factory, registry, clock)
    restarted_handler = WorkHandler(
        session_factory=uow_factory,
        runtime=restarted,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )
    assert restarted_handler.handle(payload, delivery_count=2) is AckDecision.ACK
    assert load_operation(uow_factory, ids.operation_id).state is OperationState.UNKNOWN
    assert len(store.all_resources()) == 1


def test_worker_bounds_poison_and_missing_operation_delivery(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> None:
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=2,
    )
    assert handler.handle(b"not-json", delivery_count=1) is AckDecision.TERM
    missing = WorkMessageV1(
        contract_version=CONTRACT_VERSION,
        message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f003"),
        outbox_event_id=OpaqueId(value="00000000-0000-4000-8000-00000000f004"),
        operation_id=OpaqueId(value="00000000-0000-4000-8000-00000000f005"),
        expected_operation_version=1,
        command=WorkCommand.EXECUTE,
        correlation_id=None,
        created_at=clock.now(),
    )
    encoded = encode_work_message(missing)
    assert handler.handle(encoded, delivery_count=1) is AckDecision.NAK
    assert handler.handle(encoded, delivery_count=2) is AckDecision.TERM


def test_terminal_delivery_is_quarantined_before_acknowledgement(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> None:
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=2,
    )
    publisher = RecordingPublisher()
    message = FakeJetStreamMessage(b"not-json")

    decision = asyncio.run(
        JetStreamConsumer(
            handler,
            quarantine_publisher=publisher,
        ).handle(cast(Msg, message))
    )

    assert decision is AckDecision.TERM
    assert message.termed is True
    assert message.naked is False
    assert publisher.messages[0][0] == "stateback.quarantine.v1"
    diagnostic = json.loads(publisher.messages[0][1])
    assert diagnostic["diagnostic_type"] == "POISON_MESSAGE"


def test_database_outage_exhaustion_retains_replayable_work(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    submitted = runtime.submit(make_submit(seq))
    assert submitted.operation is not None
    recovery, compensation = services(uow_factory, registry, clock)
    unavailable_engine = create_engine_from_url(
        "postgresql+psycopg://127.0.0.1:1/stateback?connect_timeout=1"
    )
    unavailable_factory = session_factory(unavailable_engine)
    handler = WorkHandler(
        session_factory=unavailable_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=2,
    )
    with unit_of_work(uow_factory) as uow:
        outbox = uow.outbox_events.list_pending_for_claim(1)[0]
    payload = encode_work_message(
        WorkMessageV1(
            contract_version=CONTRACT_VERSION,
            message_id=OpaqueId(value="00000000-0000-4000-8000-00000000f008"),
            outbox_event_id=outbox.event_id,
            operation_id=outbox.aggregate_id,
            expected_operation_version=outbox.operation_version,
            command=outbox.command,
            correlation_id=outbox.correlation_id,
            created_at=outbox.created_at,
        )
    )
    try:
        assert handler.handle(payload, delivery_count=1) is AckDecision.NAK
        assert handler.handle(payload, delivery_count=2) is AckDecision.TERM

        publisher = RecordingPublisher()
        message = FakeJetStreamMessage(payload)
        decision = asyncio.run(
            JetStreamConsumer(
                handler,
                quarantine_publisher=publisher,
            ).handle(cast(Msg, message))
        )
        assert decision is AckDecision.TERM
        assert message.termed is True
        diagnostic = json.loads(publisher.messages[0][1])
        assert diagnostic["diagnostic_type"] == "DELIVERY_EXHAUSTED"
        assert diagnostic["operation_id"] == submitted.operation.operation_id.value
        assert diagnostic["replay_payload_base64"] is not None
    finally:
        unavailable_engine.dispose()


def test_quarantine_publish_failure_naks_instead_of_losing_work(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
) -> None:
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=1,
    )
    publisher = RecordingPublisher(fail_after_publish=True)
    message = FakeJetStreamMessage(b"not-json")
    decision = asyncio.run(
        JetStreamConsumer(
            handler,
            quarantine_publisher=publisher,
        ).handle(cast(Msg, message))
    )
    assert decision is AckDecision.NAK
    assert message.naked is True
    assert message.termed is False


def test_real_jetstream_redelivery_after_durable_handling_is_safe(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    recovery, compensation = services(uow_factory, registry, clock)
    handler = WorkHandler(
        session_factory=uow_factory,
        runtime=runtime,
        recovery=recovery,
        compensation=compensation,
        max_deliveries=3,
    )

    async def scenario() -> None:
        client = await nats.connect(os.environ["STATEBACK_NATS_URL"])
        context = client.jetstream()
        stream = "STATEBACK_PHASE8_RUNTIME"
        try:
            try:
                await context.delete_stream(stream)
            except Exception:
                pass
            await context.add_stream(
                name=stream,
                subjects=["stateback.work.v1", "stateback.quarantine.v1"],
            )
            relay = OutboxRelay(
                session_factory=uow_factory,
                publisher=JetStreamPublisher(context),
                clock=clock,
                message_ids=FixedMessageIds(),
            )
            assert await relay.publish_pending(limit=1) == 1
            subscription = await context.pull_subscribe(
                "stateback.work.v1",
                durable="stateback-phase8-runtime",
                stream=stream,
            )
            first = (await subscription.fetch(1, timeout=2))[0]
            assert (
                handler.handle(first.data, delivery_count=first.metadata.num_delivered)
                is AckDecision.ACK
            )
            await first.nak()
            redelivered = (await subscription.fetch(1, timeout=2))[0]
            assert (
                await JetStreamConsumer(
                    handler,
                    quarantine_publisher=JetStreamPublisher(context),
                ).handle(redelivered)
                is AckDecision.ACK
            )
            poison = FakeJetStreamMessage(b"not-json")
            assert (
                await JetStreamConsumer(
                    handler,
                    quarantine_publisher=JetStreamPublisher(context),
                ).handle(cast(Msg, poison))
                is AckDecision.TERM
            )
            quarantine = await context.pull_subscribe(
                "stateback.quarantine.v1",
                durable="stateback-phase8-quarantine",
                stream=stream,
            )
            diagnostic_message = (await quarantine.fetch(1, timeout=2))[0]
            diagnostic = json.loads(diagnostic_message.data)
            assert diagnostic["diagnostic_type"] == "POISON_MESSAGE"
            await diagnostic_message.ack()
        finally:
            try:
                await context.delete_stream(stream)
            finally:
                await client.close()

    asyncio.run(scenario())
    assert (
        load_operation(uow_factory, ids.operation_id).state is OperationState.SUCCEEDED
    )
    assert len(store.all_resources()) == 1
