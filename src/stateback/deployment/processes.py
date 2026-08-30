"""Runnable API, relay, and worker processes for the self-hosted topology."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import nats
from fastapi import FastAPI
from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    DiscardPolicy,
    ReplayPolicy,
    RetentionPolicy,
    StorageType,
    StoreCompression,
    StreamConfig,
)
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError as NatsNotFoundError
from sqlalchemy import text

from stateback.api import create_app
from stateback.deployment.composition import build_services
from stateback.deployment.config import positive_int_env, read_secret_file, required_env
from stateback.domain.ids import OpaqueId
from stateback.messaging.codec import QuarantineDiagnostic, decode_quarantine_diagnostic
from stateback.messaging.nats import (
    QUARANTINE_SUBJECT_V1,
    JetStreamConsumer,
    JetStreamPublisher,
)
from stateback.messaging.relay import WORK_SUBJECT_V1, OutboxRelay
from stateback.messaging.worker import WorkHandler
from stateback.persistence.engine import create_engine_from_env, session_factory
from stateback.runtime.clock import SystemClock

STREAM_NAME = "STATEBACK_V1"
CONSUMER_NAME = "stateback-worker-v1"
QUARANTINE_STREAM_NAME = "STATEBACK_QUARANTINE_V1"
QUARANTINE_CONSUMER_NAME = "stateback-quarantine-operator-v1"
MAX_STREAM_MESSAGE_BYTES = 64 * 1024
PROCESS_NAMES = (
    "api",
    "relay",
    "worker",
    "health",
    "nats-init",
    "db-privileges",
    "quarantine-inspect",
    "quarantine-replay",
    "quarantine-discard",
)

_RUNTIME_TABLES = (
    "operations",
    "execution_attempts",
    "policy_decisions",
    "approvals",
    "verifications",
    "compensations",
    "compensation_attempts",
    "audit_events",
    "outbox_events",
    "reconciliation_decisions",
)
_RUNTIME_MUTABLE_TABLES = (
    "operations",
    "execution_attempts",
    "approvals",
    "verifications",
    "compensations",
    "compensation_attempts",
    "outbox_events",
)


class StableMessageIds:
    def for_outbox(self, event_id: OpaqueId) -> OpaqueId:
        return OpaqueId(
            value=str(
                uuid5(NAMESPACE_URL, f"stateback:outbox:{event_id.value}:message")
            )
        )


def create_api_application() -> FastAPI:
    services = build_services(require_auth=True, execute_providers=False)
    if services.authenticator is None:
        raise RuntimeError("API authentication configuration is required")
    app = create_app(
        service=services.application,
        authenticator=services.authenticator,
    )

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> dict[str, str]:
        with services.session_factory() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    if os.environ.get("STATEBACK_SERVE_OPERATOR_UI") == "1":
        from importlib.resources import files

        from stateback.operator_ui import SpaStaticFiles

        static = files("stateback.operator_ui").joinpath("static")
        app.mount(
            "/", SpaStaticFiles(directory=str(static), html=True), name="operator-ui"
        )

    return app


def readiness_path() -> Path:
    return Path(os.environ.get("STATEBACK_READINESS_PATH", "/tmp/stateback-ready"))


def _stream_config() -> StreamConfig:
    return StreamConfig(
        name=STREAM_NAME,
        subjects=[WORK_SUBJECT_V1],
        retention=RetentionPolicy.WORK_QUEUE,
        max_consumers=1,
        max_msgs=-1,
        max_msgs_per_subject=-1,
        discard=DiscardPolicy.OLD,
        discard_new_per_subject=False,
        storage=StorageType.FILE,
        num_replicas=positive_int_env("STATEBACK_NATS_REPLICAS", 1, maximum=5),
        max_age=30 * 24 * 60 * 60,
        max_bytes=768 * 1024 * 1024,
        max_msg_size=MAX_STREAM_MESSAGE_BYTES,
        no_ack=False,
        duplicate_window=120,
        sealed=False,
        deny_delete=True,
        deny_purge=True,
        allow_rollup_hdrs=False,
        allow_direct=False,
        mirror_direct=False,
        compression=StoreCompression.NONE,
        allow_msg_ttl=False,
    )


def _quarantine_stream_config() -> StreamConfig:
    return StreamConfig(
        name=QUARANTINE_STREAM_NAME,
        subjects=[QUARANTINE_SUBJECT_V1],
        retention=RetentionPolicy.WORK_QUEUE,
        max_consumers=1,
        max_msgs=10_000,
        max_msgs_per_subject=-1,
        discard=DiscardPolicy.NEW,
        discard_new_per_subject=False,
        storage=StorageType.FILE,
        num_replicas=positive_int_env("STATEBACK_NATS_REPLICAS", 1, maximum=5),
        max_age=30 * 24 * 60 * 60,
        max_bytes=256 * 1024 * 1024,
        max_msg_size=MAX_STREAM_MESSAGE_BYTES,
        no_ack=False,
        duplicate_window=120,
        sealed=False,
        deny_delete=True,
        deny_purge=True,
        allow_rollup_hdrs=False,
        allow_direct=False,
        mirror_direct=False,
        compression=StoreCompression.NONE,
        allow_msg_ttl=False,
    )


def _stream_is_controlled(actual: StreamConfig, expected: StreamConfig) -> bool:
    return (
        actual.subjects == expected.subjects
        and actual.retention == expected.retention
        and actual.max_consumers == expected.max_consumers
        and actual.max_msgs == expected.max_msgs
        and actual.max_msgs_per_subject == expected.max_msgs_per_subject
        and actual.discard == expected.discard
        and actual.discard_new_per_subject == expected.discard_new_per_subject
        and actual.storage == expected.storage
        and actual.num_replicas == expected.num_replicas
        and actual.max_age == expected.max_age
        and actual.max_bytes == expected.max_bytes
        and actual.max_msg_size == expected.max_msg_size
        and actual.no_ack == expected.no_ack
        and actual.duplicate_window == expected.duplicate_window
        and actual.sealed == expected.sealed
        and actual.deny_delete is True
        and actual.deny_purge is True
        and actual.allow_rollup_hdrs == expected.allow_rollup_hdrs
        and actual.allow_direct == expected.allow_direct
        and actual.mirror_direct == expected.mirror_direct
        and actual.allow_msg_ttl == expected.allow_msg_ttl
        and actual.allow_msg_schedules == expected.allow_msg_schedules
        and actual.allow_atomic == expected.allow_atomic
        and actual.allow_batched == expected.allow_batched
        and actual.first_seq == expected.first_seq
        and actual.placement == expected.placement
        and actual.compression == expected.compression
        and actual.persist_mode == expected.persist_mode
        and actual.subject_delete_marker_ttl == expected.subject_delete_marker_ttl
        and actual.mirror is None
        and actual.sources is None
        and actual.republish is None
        and actual.subject_transform is None
        and (
            actual.consumer_limits is None
            or (
                actual.consumer_limits.inactive_threshold is None
                and actual.consumer_limits.max_ack_pending is None
            )
        )
    )


def _consumer_config() -> ConsumerConfig:
    return ConsumerConfig(
        durable_name=CONSUMER_NAME,
        deliver_policy=DeliverPolicy.ALL,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=60,
        max_deliver=positive_int_env("STATEBACK_WORKER_MAX_DELIVERIES", 5, maximum=100),
        backoff=None,
        filter_subject=WORK_SUBJECT_V1,
        replay_policy=ReplayPolicy.INSTANT,
        max_waiting=512,
        max_ack_pending=1,
        num_replicas=0,
    )


def _quarantine_consumer_config() -> ConsumerConfig:
    return ConsumerConfig(
        name=QUARANTINE_CONSUMER_NAME,
        durable_name=QUARANTINE_CONSUMER_NAME,
        deliver_policy=DeliverPolicy.ALL,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=300,
        max_deliver=20,
        filter_subject=QUARANTINE_SUBJECT_V1,
        replay_policy=ReplayPolicy.INSTANT,
        max_waiting=16,
        max_ack_pending=1,
        num_replicas=0,
    )


def _consumer_is_controlled(actual: ConsumerConfig, expected: ConsumerConfig) -> bool:
    fields = (
        "durable_name",
        "deliver_policy",
        "opt_start_seq",
        "opt_start_time",
        "ack_policy",
        "ack_wait",
        "max_deliver",
        "backoff",
        "filter_subject",
        "filter_subjects",
        "replay_policy",
        "rate_limit_bps",
        "sample_freq",
        "max_waiting",
        "max_ack_pending",
        "flow_control",
        "idle_heartbeat",
        "headers_only",
        "deliver_subject",
        "deliver_group",
        "inactive_threshold",
        "num_replicas",
        "mem_storage",
        "pause_until",
    )
    return all(getattr(actual, field) == getattr(expected, field) for field in fields)


async def provision_jetstream() -> None:
    nats_url = read_secret_file("STATEBACK_NATS_BOOTSTRAP_URL_FILE")
    if nats_url is None:
        nats_url = required_env("STATEBACK_NATS_BOOTSTRAP_URL")
    client = await nats.connect(nats_url)
    context = client.jetstream()
    try:
        await _provision_stream(
            context,
            stream_name=STREAM_NAME,
            consumer_name=CONSUMER_NAME,
            expected_stream=_stream_config(),
            expected_consumer=_consumer_config(),
        )
        await _provision_stream(
            context,
            stream_name=QUARANTINE_STREAM_NAME,
            consumer_name=QUARANTINE_CONSUMER_NAME,
            expected_stream=_quarantine_stream_config(),
            expected_consumer=_quarantine_consumer_config(),
        )
    finally:
        await client.close()


async def _provision_stream(
    context: JetStreamContext,
    *,
    stream_name: str,
    consumer_name: str,
    expected_stream: StreamConfig,
    expected_consumer: ConsumerConfig,
) -> None:
    try:
        stream = await context.stream_info(stream_name)
    except NatsNotFoundError:
        stream = await context.add_stream(config=expected_stream)
    if not _stream_is_controlled(stream.config, expected_stream):
        raise RuntimeError("existing Stateback JetStream configuration is unsafe")

    try:
        consumer = await context.consumer_info(stream_name, consumer_name)
    except NatsNotFoundError:
        consumer = await context.add_consumer(stream_name, config=expected_consumer)
    if not _consumer_is_controlled(consumer.config, expected_consumer):
        raise RuntimeError("existing Stateback consumer configuration is unsafe")


async def _jetstream() -> tuple[NatsClient, JetStreamContext]:
    nats_url = read_secret_file("STATEBACK_NATS_URL_FILE")
    if nats_url is None:
        nats_url = required_env("STATEBACK_NATS_URL")

    async def disconnected() -> None:
        readiness_path().unlink(missing_ok=True)

    async def reconnected() -> None:
        readiness_path().write_text("ready\n", encoding="ascii")

    client = await nats.connect(
        nats_url,
        allow_reconnect=True,
        max_reconnect_attempts=-1,
        reconnect_time_wait=1,
        disconnected_cb=disconnected,
        reconnected_cb=reconnected,
    )
    context = client.jetstream()
    expected_stream = _stream_config()
    expected_consumer = _consumer_config()
    try:
        stream = await context.stream_info(STREAM_NAME)
        if not _stream_is_controlled(stream.config, expected_stream):
            raise RuntimeError("existing Stateback JetStream configuration is unsafe")
        consumer = await context.consumer_info(STREAM_NAME, CONSUMER_NAME)
        if not _consumer_is_controlled(consumer.config, expected_consumer):
            raise RuntimeError("existing Stateback consumer configuration is unsafe")
        quarantine_stream = await context.stream_info(QUARANTINE_STREAM_NAME)
        if not _stream_is_controlled(
            quarantine_stream.config, _quarantine_stream_config()
        ):
            raise RuntimeError("existing Stateback quarantine stream is unsafe")
        quarantine_consumer = await context.consumer_info(
            QUARANTINE_STREAM_NAME, QUARANTINE_CONSUMER_NAME
        )
        if not _consumer_is_controlled(
            quarantine_consumer.config, _quarantine_consumer_config()
        ):
            raise RuntimeError("existing Stateback quarantine consumer is unsafe")
    except Exception:
        await client.close()
        raise
    return client, context


async def _quarantine_message() -> tuple[
    NatsClient, JetStreamContext, Msg, QuarantineDiagnostic
]:
    nats_url = read_secret_file("STATEBACK_NATS_QUARANTINE_URL_FILE")
    if nats_url is None:
        nats_url = required_env("STATEBACK_NATS_QUARANTINE_URL")
    client = await nats.connect(nats_url)
    context = client.jetstream()
    try:
        stream = await context.stream_info(QUARANTINE_STREAM_NAME)
        consumer = await context.consumer_info(
            QUARANTINE_STREAM_NAME, QUARANTINE_CONSUMER_NAME
        )
        if not _stream_is_controlled(stream.config, _quarantine_stream_config()):
            raise RuntimeError("existing Stateback quarantine stream is unsafe")
        if not _consumer_is_controlled(consumer.config, _quarantine_consumer_config()):
            raise RuntimeError("existing Stateback quarantine consumer is unsafe")
        subscription = await context.pull_subscribe(
            QUARANTINE_SUBJECT_V1,
            durable=QUARANTINE_CONSUMER_NAME,
            stream=QUARANTINE_STREAM_NAME,
        )
        message = (await subscription.fetch(1, timeout=5))[0]
        diagnostic = decode_quarantine_diagnostic(message.data)
        return client, context, message, diagnostic
    except Exception:
        await client.close()
        raise


async def inspect_quarantine() -> None:
    client, _context, message, diagnostic = await _quarantine_message()
    try:
        print(json.dumps(diagnostic.to_wire(), sort_keys=True, separators=(",", ":")))
        await message.nak()
    finally:
        await client.close()


async def replay_quarantine() -> None:
    expected_message_id = required_env("STATEBACK_QUARANTINE_REPLAY_MESSAGE_ID")
    client, context, message, diagnostic = await _quarantine_message()
    try:
        if (
            diagnostic.message is None
            or diagnostic.replay_payload is None
            or diagnostic.message.message_id.value != expected_message_id
        ):
            await message.nak()
            raise RuntimeError("quarantine replay confirmation does not match")
        await context.publish(WORK_SUBJECT_V1, diagnostic.replay_payload)
        await message.ack_sync(timeout=5)
        print(
            json.dumps(
                {
                    "status": "replayed",
                    "message_id": diagnostic.message.message_id.value,
                    "operation_id": diagnostic.message.operation_id.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        await client.close()


async def discard_quarantine() -> None:
    expected_digest = required_env("STATEBACK_QUARANTINE_DISCARD_SHA256")
    client, _context, message, diagnostic = await _quarantine_message()
    try:
        if diagnostic.payload_sha256 != expected_digest:
            await message.nak()
            raise RuntimeError("quarantine discard confirmation does not match")
        await message.ack_sync(timeout=5)
        print(
            json.dumps(
                {"status": "discarded", "payload_sha256": expected_digest},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    finally:
        await client.close()


def _stop_event() -> asyncio.Event:
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, event.set)
        except NotImplementedError:
            pass
    return event


async def run_relay() -> None:
    marker = readiness_path()
    marker.unlink(missing_ok=True)
    factory = session_factory(create_engine_from_env())
    client, context = await _jetstream()
    relay = OutboxRelay(
        session_factory=factory,
        publisher=JetStreamPublisher(context),
        clock=SystemClock(),
        message_ids=StableMessageIds(),
    )
    stop = _stop_event()
    batch = positive_int_env("STATEBACK_RELAY_BATCH", 100, maximum=1000)
    interval_ms = positive_int_env("STATEBACK_RELAY_INTERVAL_MS", 250, maximum=60_000)
    recovery_after_seconds = positive_int_env(
        "STATEBACK_OUTBOX_RECOVERY_AFTER_SECONDS", 300, maximum=86_400
    )
    recovery_max_republishes = positive_int_env(
        "STATEBACK_OUTBOX_RECOVERY_MAX_REPUBLISHES", 3, maximum=20
    )
    marker.write_text("ready\n", encoding="ascii")
    try:
        while not stop.is_set():
            recovered = relay.recover_stranded(
                limit=batch,
                after_seconds=recovery_after_seconds,
                max_recoveries=recovery_max_republishes,
            )
            published = await relay.publish_pending(limit=batch)
            if recovered == 0 and published == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval_ms / 1000)
                except TimeoutError:
                    pass
    finally:
        marker.unlink(missing_ok=True)
        await client.drain()


async def run_worker(*, development: bool = False) -> None:
    marker = readiness_path()
    marker.unlink(missing_ok=True)
    demo_directory = None
    if development:
        raw_demo_directory = os.environ.get("STATEBACK_DEMO_UNKNOWN_ARM_DIRECTORY")
        if raw_demo_directory is None:
            raise RuntimeError("local demo arm directory is required")
        demo_directory = Path(raw_demo_directory)
        if not demo_directory.is_dir() or demo_directory.is_symlink():
            raise RuntimeError("local demo arm directory is unsafe")
    services = build_services(
        require_auth=False,
        execute_providers=True,
        development_demo_arm_directory=demo_directory,
    )
    max_deliveries = positive_int_env("STATEBACK_WORKER_MAX_DELIVERIES", 5, maximum=100)
    handler = WorkHandler(
        session_factory=services.session_factory,
        runtime=services.runtime,
        recovery=services.recovery,
        compensation=services.compensation,
        max_deliveries=max_deliveries,
    )
    client, context = await _jetstream()
    subscription = await context.pull_subscribe(
        WORK_SUBJECT_V1,
        durable=CONSUMER_NAME,
        stream=STREAM_NAME,
        config=_consumer_config(),
    )
    consumer = JetStreamConsumer(
        handler,
        quarantine_publisher=JetStreamPublisher(context),
    )
    stop = _stop_event()
    marker.write_text("ready\n", encoding="ascii")
    try:
        while not stop.is_set():
            try:
                messages = await subscription.fetch(1, timeout=1)
            except NatsTimeoutError:
                continue
            await consumer.handle(messages[0])
    finally:
        marker.unlink(missing_ok=True)
        await client.drain()


def check_worker_health() -> None:
    if not readiness_path().is_file():
        raise RuntimeError("process is not ready")
    engine = create_engine_from_env()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def configure_database_privileges() -> None:
    """Install the exact DML grants required by the 0.1.0 persistence model."""

    engine = create_engine_from_env()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public "
                    "FROM stateback_runtime"
                )
            )
            connection.execute(
                text(
                    "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
                    "FROM stateback_runtime"
                )
            )
            connection.execute(
                text(
                    "GRANT SELECT, INSERT ON TABLE "
                    + ", ".join(_RUNTIME_TABLES)
                    + " TO stateback_runtime"
                )
            )
            connection.execute(
                text(
                    "GRANT UPDATE ON TABLE "
                    + ", ".join(_RUNTIME_MUTABLE_TABLES)
                    + " TO stateback_runtime"
                )
            )
    finally:
        engine.dispose()


def run_process(process: str) -> None:
    if process not in PROCESS_NAMES:
        raise RuntimeError(f"unknown Stateback process: {process}")
    if process == "health":
        check_worker_health()
        return
    if process == "api":
        import uvicorn

        uvicorn.run(
            "stateback.deployment.processes:create_api_application",
            factory=True,
            host=os.environ.get("STATEBACK_API_HOST", "0.0.0.0"),
            port=positive_int_env("STATEBACK_API_PORT", 8080, maximum=65_535),
            proxy_headers=False,
            server_header=False,
        )
        return
    if process == "nats-init":
        asyncio.run(provision_jetstream())
        return
    if process == "db-privileges":
        configure_database_privileges()
        return
    if process == "quarantine-inspect":
        asyncio.run(inspect_quarantine())
        return
    if process == "quarantine-replay":
        asyncio.run(replay_quarantine())
        return
    if process == "quarantine-discard":
        asyncio.run(discard_quarantine())
        return
    asyncio.run(run_relay() if process == "relay" else run_worker())


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="stateback")
    parser.add_argument(
        "process",
        choices=PROCESS_NAMES,
    )
    args = parser.parse_args()
    run_process(args.process)
