from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]


def test_runtime_source_does_not_call_update_cas() -> None:
    for path in (_ROOT / "src" / "stateback" / "runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "update_cas" not in text, path


def test_runtime_source_does_not_call_verify_or_compensate() -> None:
    for path in (_ROOT / "src" / "stateback" / "runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "adapter.verify" not in text, path
        assert ".compensate(" not in text, path


def test_policy_source_does_not_import_runtime_or_transitions() -> None:
    for path in (_ROOT / "src" / "stateback" / "policy").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "stateback.runtime" not in text, path
        assert "stateback.transitions" not in text, path
        assert "stateback.persistence" not in text, path
