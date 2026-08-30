from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from stateback.cli.config import ProjectConfigError, load_project_config
from stateback.cli.init import initialize
from stateback.cli.main import main
from stateback.cli.project import ProjectFileError, find_project_root

pytestmark = pytest.mark.unit


def test_fresh_initialization_is_safe_and_default_deny(tmp_path: Path) -> None:
    result = initialize(tmp_path)

    assert result.status == "initialized"
    assert set(result.created) == {
        "stateback.toml",
        "stateback.policy.json",
        ".stateback/.gitignore",
        ".stateback/auth.json",
    }
    assert (tmp_path / ".stateback/.gitignore").read_text() == "*\n!.gitignore\n"
    policy = json.loads((tmp_path / "stateback.policy.json").read_text())
    assert policy["rules"][0]["verdict"] == "REQUIRE_APPROVAL"
    assert set(policy["rules"][0]["actions"]) == {
        "create_issue",
        "create_issue_comment",
        "add_label",
        "create_pull_request",
        "merge_pull_request",
    }
    assert len(policy["rules"]) == 1

    auth = json.loads((tmp_path / ".stateback/auth.json").read_text())
    tokens = [identity["token"] for identity in auth["identities"]]
    assert len(tokens) == len(set(tokens)) == 2
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / ".stateback/auth.json").stat().st_mode) == 0o600


def test_second_initialization_preserves_credentials_and_configuration(
    tmp_path: Path,
) -> None:
    initialize(tmp_path)
    auth = tmp_path / ".stateback/auth.json"
    first_auth = auth.read_bytes()
    config = tmp_path / "stateback.toml"
    config.write_text(config.read_text().replace("api_port = 8080", "api_port = 8081"))

    result = initialize(tmp_path)

    assert result.status == "already_initialized"
    assert auth.read_bytes() == first_auth
    assert "api_port = 8081" in config.read_text()


def test_partial_initialization_only_creates_missing_files(tmp_path: Path) -> None:
    initialize(tmp_path)
    policy = tmp_path / "stateback.policy.json"
    policy.unlink()
    auth_before = (tmp_path / ".stateback/auth.json").read_bytes()

    result = initialize(tmp_path)

    assert result.created == ("stateback.policy.json",)
    assert (tmp_path / ".stateback/auth.json").read_bytes() == auth_before


def test_invalid_existing_configuration_fails_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "stateback.toml").write_text("not = [valid")
    original = (tmp_path / "stateback.toml").read_bytes()

    with pytest.raises(ProjectConfigError, match="unreadable or invalid"):
        initialize(tmp_path)

    assert (tmp_path / "stateback.toml").read_bytes() == original
    assert not (tmp_path / ".stateback/auth.json").exists()


def test_json_output_never_contains_generated_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["stateback", "init", "--json"])
    main()
    output = capsys.readouterr().out
    auth = json.loads((tmp_path / ".stateback/auth.json").read_text())

    assert json.loads(output)["status"] == "initialized"
    for identity in auth["identities"]:
        assert identity["token"] not in output


def test_project_discovery_walks_to_parent(tmp_path: Path) -> None:
    initialize(tmp_path)
    nested = tmp_path / "src" / "agent"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path.resolve()
    assert load_project_config(tmp_path / "stateback.toml").root == tmp_path.resolve()


def test_symlinked_state_directory_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / ".stateback").symlink_to(target, target_is_directory=True)

    with pytest.raises(ProjectFileError, match="unsafe project directory"):
        initialize(tmp_path)


def test_mcp_help_and_config_are_public_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["stateback", "mcp", "--print-config"])
    main()
    assert json.loads(capsys.readouterr().out) == {
        "command": "stateback",
        "args": ["mcp"],
    }


def test_mcp_command_starts_authenticated_stdio_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, base_url: str, token: str) -> None:
            observed["client"] = (base_url, token)

        def close(self) -> None:
            observed["closed"] = True

    class FakeServer:
        def run(self, transport: str) -> None:
            observed["transport"] = transport

    monkeypatch.setenv("STATEBACK_API_URL", "https://stateback.test")
    monkeypatch.setenv("STATEBACK_API_TOKEN", "caller-token")
    monkeypatch.setattr("stateback.cli.mcp.StatebackClient", FakeClient)
    monkeypatch.setattr(
        "stateback.cli.mcp.create_api_mcp_server", lambda _client: FakeServer()
    )
    monkeypatch.setattr(sys, "argv", ["stateback", "mcp"])

    main()

    assert observed == {
        "client": ("https://stateback.test", "caller-token"),
        "transport": "stdio",
        "closed": True,
    }
