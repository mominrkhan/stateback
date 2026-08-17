from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_COMPENSATION = _ROOT / "src" / "stateback" / "compensation"


def test_update_cas_not_in_compensation_package() -> None:
    for path in _COMPENSATION.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "update_cas" not in text, path


def test_insert_request_not_in_compensation_package() -> None:
    for path in _COMPENSATION.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "insert_request" not in text, path


def test_adapter_execute_not_in_compensation_package() -> None:
    for path in _COMPENSATION.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "adapter.execute" not in text, path
