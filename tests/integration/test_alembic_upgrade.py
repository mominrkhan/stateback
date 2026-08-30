from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_alembic_upgrade_head_is_noop_success() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_alembic_current_is_runnable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


def _connect() -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=os.environ["STATEBACK_POSTGRES_HOST"],
        port=os.environ["STATEBACK_POSTGRES_PORT"],
        dbname=os.environ["STATEBACK_POSTGRES_DB"],
        user=os.environ["STATEBACK_POSTGRES_USER"],
        password=os.environ["STATEBACK_POSTGRES_PASSWORD"],
    )


def test_alembic_head_is_0002_operator_query_indexes() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
    assert row is not None
    assert row[0] == "0002_operator_query_indexes"


def test_alembic_upgrade_creates_journal_tables() -> None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            names = [str(item[0]) for item in cur.fetchall()]
    assert names == [
        "alembic_version",
        "approvals",
        "audit_events",
        "compensation_attempts",
        "compensations",
        "execution_attempts",
        "operations",
        "outbox_events",
        "policy_decisions",
        "reconciliation_decisions",
        "verifications",
    ]
