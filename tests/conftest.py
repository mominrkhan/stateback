"""Phase 0 pytest hooks.

Integration tests run if and only if STATEBACK_RUN_INTEGRATION=1.
Auto-detecting local services is rejected: it is nondeterministic and can
accidentally hit a non-Compose PostgreSQL on the implementer machine.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import pytest

INTEGRATION_ENABLED = os.environ.get("STATEBACK_RUN_INTEGRATION") == "1"

REQUIRED_INTEGRATION_ENV = (
    "STATEBACK_POSTGRES_HOST",
    "STATEBACK_POSTGRES_PORT",
    "STATEBACK_POSTGRES_DB",
    "STATEBACK_POSTGRES_USER",
    "STATEBACK_POSTGRES_PASSWORD",
    "STATEBACK_DATABASE_URL",
    "STATEBACK_NATS_URL",
    "STATEBACK_NATS_MONITOR_URL",
)


def pytest_configure(config: pytest.Config) -> None:
    if not INTEGRATION_ENABLED:
        return
    missing = [name for name in REQUIRED_INTEGRATION_ENV if not os.environ.get(name)]
    if missing:
        raise pytest.UsageError(
            "STATEBACK_RUN_INTEGRATION=1 requires environment variables: "
            + ", ".join(missing)
        )


def pytest_collection_modifyitems(
    config: pytest.Config, items: Iterable[pytest.Item]
) -> None:
    if INTEGRATION_ENABLED:
        return
    skip = pytest.mark.skip(
        reason=(
            "set STATEBACK_RUN_INTEGRATION=1 after `docker compose up -d --wait` "
            "and exporting `.env`"
        )
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
