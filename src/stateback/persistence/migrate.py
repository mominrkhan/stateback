"""Programmatic migrations that do not depend on a repository checkout."""

from __future__ import annotations

from importlib.resources import files

from alembic import command
from alembic.config import Config


def upgrade_head(database_url: str) -> None:
    """Upgrade one database to the migration head packaged in the wheel."""

    config = Config()
    config.set_main_option(
        "script_location", str(files("stateback.persistence.migrations"))
    )
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
