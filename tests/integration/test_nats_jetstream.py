from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from asyncio import run

import nats
import pytest

from stateback.messaging.nats import JetStreamPublisher

pytestmark = [pytest.mark.integration, pytest.mark.nats]


def test_jetstream_enabled_via_jsz() -> None:
    base = os.environ["STATEBACK_NATS_MONITOR_URL"].rstrip("/")
    url = f"{base}/jsz"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AssertionError(
            f"GET {url} returned HTTP {exc.code}; JetStream is not enabled"
        ) from exc
    assert status == 200
    assert isinstance(payload, dict)
    assert "config" in payload
    store_dir = payload["config"].get("store_dir")
    assert store_dir, "JetStream config.store_dir must be set"


def test_jetstream_publisher_receives_server_ack() -> None:
    async def scenario() -> None:
        client = await nats.connect(os.environ["STATEBACK_NATS_URL"])
        context = client.jetstream()
        stream = "STATEBACK_PHASE8_TEST"
        subject = "stateback.phase8.test"
        try:
            try:
                await context.delete_stream(stream)
            except Exception:
                pass
            await context.add_stream(name=stream, subjects=[subject])
            publisher = JetStreamPublisher(context)
            await publisher.publish(subject, b"phase8")
            subscription = await context.pull_subscribe(
                subject, durable="stateback-phase8-test", stream=stream
            )
            messages = await subscription.fetch(1, timeout=2)
            assert messages[0].data == b"phase8"
            await messages[0].ack()
        finally:
            try:
                await context.delete_stream(stream)
            finally:
                await client.close()

    run(scenario())
