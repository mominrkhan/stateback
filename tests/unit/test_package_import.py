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
    assert module.__version__ == "0.0.0"
    assert domain.CONTRACT_VERSION == "v1"
