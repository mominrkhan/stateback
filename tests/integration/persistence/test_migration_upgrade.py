from __future__ import annotations

from importlib.resources import files

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from stateback.persistence.engine import session_factory
from stateback.persistence.uow import unit_of_work
from tests.integration.persistence.conftest import make_operation
from tests.unit.domain.fixtures import OP_ID

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_populated_0001_upgrades_to_head_without_losing_operations(
    engine: Engine, database_url: str
) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(files("stateback.persistence.migrations"))
    )
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001_journal_v1")
    factory = session_factory(engine)
    with unit_of_work(factory) as uow:
        uow.operations.insert(make_operation())

    command.upgrade(config, "head")

    with unit_of_work(factory) as uow:
        loaded = uow.operations.get(OP_ID)
    assert loaded is not None
    indexes = {item["name"] for item in inspect(engine).get_indexes("operations")}
    assert "ix_operations_created_at_operation_id" in indexes
    assert "ix_operations_state_created_at_operation_id" in indexes
    assert "ix_operations_provider_created_at_operation_id" in indexes
