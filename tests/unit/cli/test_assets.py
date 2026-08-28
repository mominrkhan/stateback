from __future__ import annotations

import os
import subprocess
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest

from stateback.operator_ui import SpaStaticFiles

pytestmark = pytest.mark.unit


def test_installed_package_contains_local_runtime_assets() -> None:
    compose = files("stateback.cli.assets").joinpath("compose.dev.yaml")
    migration = files("stateback.persistence.migrations").joinpath(
        "versions/0001_journal_v1.py"
    )
    ui = files("stateback.operator_ui").joinpath("static/index.html")

    assert compose.is_file()
    assert migration.is_file()
    assert ui.is_file()


def test_spa_static_files_falls_back_to_index() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    static = files("stateback.operator_ui").joinpath("static")
    app.mount("/", SpaStaticFiles(directory=str(static), html=True))

    assert TestClient(app).get("/").status_code == 200
    response = TestClient(app).get("/operations/example")
    assert response.status_code == 200
    assert "Stateback Operator" in response.text
    assert TestClient(app).get("/v1/missing").status_code == 404
    assert TestClient(app).get("/health/missing").status_code == 404


def test_built_wheel_contains_complete_local_runtime(tmp_path: Path) -> None:
    root = Path(__file__).parents[3]
    environment = dict(os.environ)
    environment["SOURCE_DATE_EPOCH"] = "0"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert "stateback/cli/assets/compose.dev.yaml" in names
    assert "stateback/persistence/migrations/versions/0001_journal_v1.py" in names
    assert "stateback/operator_ui/static/index.html" in names
    assert any(
        name.startswith("stateback/operator_ui/static/assets/") for name in names
    )
