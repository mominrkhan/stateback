from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_RECOVERY = _ROOT / "src" / "stateback" / "recovery"


def test_recovery_source_does_not_call_update_cas() -> None:
    for path in _RECOVERY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "update_cas" not in text, path


def test_recovery_source_does_not_call_execute_or_compensate() -> None:
    for path in _RECOVERY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "adapter.execute" not in text, path
        assert ".compensate(" not in text, path


def test_recovery_source_does_not_insert_request() -> None:
    for path in _RECOVERY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "insert_request" not in text, path


def test_recovery_source_does_not_mark_published() -> None:
    for path in _RECOVERY.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "mark_published" not in text, path
