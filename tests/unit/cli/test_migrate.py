from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from stateback.persistence import migrate

pytestmark = pytest.mark.unit


def test_programmatic_migration_uses_packaged_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Config | None = None

    def upgrade(config: Config, revision: str) -> None:
        nonlocal captured
        captured = config
        assert revision == "head"

    monkeypatch.setattr(command, "upgrade", upgrade)
    migrate.upgrade_head("postgresql+psycopg://example.invalid/stateback")

    assert captured is not None
    script_location = captured.get_main_option("script_location")
    database_url = captured.get_main_option("sqlalchemy.url")
    assert script_location is not None
    assert database_url is not None
    assert Path(script_location).name == "migrations"
    assert database_url.endswith("/stateback")
