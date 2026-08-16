from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_postgres_select_one_and_major_version() -> None:
    conninfo = (
        f"host={os.environ['STATEBACK_POSTGRES_HOST']} "
        f"port={os.environ['STATEBACK_POSTGRES_PORT']} "
        f"dbname={os.environ['STATEBACK_POSTGRES_DB']} "
        f"user={os.environ['STATEBACK_POSTGRES_USER']} "
        f"password={os.environ['STATEBACK_POSTGRES_PASSWORD']}"
    )
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
            cur.execute("SHOW server_version")
            row = cur.fetchone()
    assert row is not None
    assert str(row[0]).startswith("16.")
