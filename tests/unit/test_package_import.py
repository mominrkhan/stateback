from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_import_stateback_version() -> None:
    import stateback

    assert stateback.__version__ == "0.1.0"


def test_import_does_not_open_sockets_or_connect_to_postgres() -> None:
    for name in list(sys.modules):
        if name == "stateback" or name.startswith("stateback."):
            sys.modules.pop(name)
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
        transitions = importlib.import_module("stateback.transitions")
        providers = importlib.import_module("stateback.providers")
        adapter = importlib.import_module("stateback.providers.reference.adapter")
        policy = importlib.import_module("stateback.policy")
        runtime = importlib.import_module("stateback.runtime")
        recovery = importlib.import_module("stateback.recovery")
        compensation = importlib.import_module("stateback.compensation")
    assert module.__version__ == "0.1.0"
    assert domain.CONTRACT_VERSION == "v1"
    assert hasattr(persistence, "create_engine_from_env")
    assert hasattr(transitions, "TransitionService")
    assert hasattr(providers, "CapabilityRegistry")
    assert hasattr(adapter, "ReferenceAdapter")
    assert hasattr(policy, "AllowAllPolicyEngine")
    assert hasattr(runtime, "SynchronousRuntime")
    assert hasattr(recovery, "RecoveryService")
    assert hasattr(compensation, "CompensationService")


def test_import_persistence_does_not_create_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STATEBACK_DATABASE_URL", raising=False)
    for name in list(sys.modules):
        if name == "stateback.persistence" or name.startswith("stateback.persistence."):
            sys.modules.pop(name)
    importlib.import_module("stateback.persistence")
