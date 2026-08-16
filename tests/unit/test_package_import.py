from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_import_stateback_version() -> None:
    import stateback

    assert stateback.__version__ == "0.0.0"


def test_import_does_not_open_sockets_or_connect_to_postgres() -> None:
    sys.modules.pop("stateback", None)
    sys.modules.pop("stateback.domain", None)
    sys.modules.pop("stateback.persistence", None)
    with (
        patch(
            "socket.socket",
            side_effect=AssertionError("socket opened during import"),
        ),
        patch(
            "socket.create_connection",
            side_effect=AssertionError("create_connection during import"),
        ),
        patch(
            "psycopg.connect",
            side_effect=AssertionError("psycopg.connect during import"),
        ),
    ):
        module = importlib.import_module("stateback")
        domain = importlib.import_module("stateback.domain")
        persistence = importlib.import_module("stateback.persistence")
    assert module.__version__ == "0.0.0"
    assert domain.CONTRACT_VERSION == "v1"
    assert hasattr(persistence, "create_engine_from_env")


def test_import_persistence_does_not_create_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STATEBACK_DATABASE_URL", raising=False)
    for name in list(sys.modules):
        if name == "stateback.persistence" or name.startswith("stateback.persistence."):
            sys.modules.pop(name)
    importlib.import_module("stateback.persistence")
