from __future__ import annotations

from pathlib import Path

import pytest

from stateback.cli.demo import DemoError, run_unknown_demo
from stateback.cli.init import initialize
from stateback.domain.enums import PrincipalType
from stateback.domain.refs import PrincipalRef
from stateback.sdk import StatebackTransportError

pytestmark = pytest.mark.unit


def test_api_transport_ambiguity_preserves_exact_demo_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    config = tmp_path / "stateback.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("enabled = false", "enabled = true"),
        encoding="utf-8",
    )
    run_directory = tmp_path / ".stateback" / "run"
    arm_directory = run_directory / "demo-unknown"
    arm_directory.mkdir(parents=True)
    (run_directory / "worker.ready").write_text("ready\n", encoding="ascii")
    monkeypatch.setattr(
        "stateback.cli.demo._local_caller",
        lambda _root: (
            "http://127.0.0.1:8080",
            "caller-token",
            PrincipalRef(type=PrincipalType.AGENT, id="demo-caller", display_name=None),
        ),
    )

    class AmbiguousClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def submit(self, **_kwargs: object) -> object:
            raise StatebackTransportError("transport_failed")

        def close(self) -> None:
            pass

    monkeypatch.setattr("stateback.cli.demo.StatebackClient", AmbiguousClient)

    with pytest.raises(DemoError, match="did not remove an unconsumed demo arm"):
        run_unknown_demo(
            owner="acme",
            repo="sandbox",
            confirm_mutation=True,
            start=tmp_path,
        )

    armed = list(arm_directory.iterdir())
    assert len(armed) == 1
    assert armed[0].read_text(encoding="ascii") == "armed\n"
