from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

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
