from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from stateback.cli.config import load_project_config
from stateback.cli.connect import (
    CommandResult,
    GitHubConnectError,
    LocalCommandRunner,
    connect_github,
)
from stateback.cli.init import initialize
from stateback.cli.project import replace_file as real_replace_file

pytestmark = pytest.mark.unit


class FakeRunner:
    def __init__(self, results: Sequence[CommandResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(arguments))
        return self.results.pop(0)


def _runner(*, token: str = "secret-test-token") -> FakeRunner:
    return FakeRunner(
        (
            CommandResult(0, ""),
            CommandResult(0, "octocat\n"),
            CommandResult(0, f"{token}\n"),
        )
    )


def test_connect_uses_gh_and_enables_existing_provider_securely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = _runner()

    result = connect_github(runner)

    assert result.account == "octocat"
    assert runner.calls == [
        ("gh", "auth", "status", "--hostname", "github.com"),
        ("gh", "api", "--hostname", "github.com", "user", "--jq", ".login"),
        ("gh", "auth", "token", "--hostname", "github.com"),
    ]
    token = tmp_path / ".stateback/secrets/github-token"
    assert token.read_text() == "secret-test-token\n"
    if os.name == "posix":
        assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert load_project_config(tmp_path / "stateback.toml").github_enabled
    assert "secret-test-token" not in capsys.readouterr().out


def test_repeated_connect_safely_replaces_the_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    connect_github(_runner(token="first-secret"))
    connect_github(_runner(token="second-secret"))

    assert (tmp_path / ".stateback/secrets/github-token").read_text() == (
        "second-secret\n"
    )
    assert (tmp_path / "stateback.toml").read_text().count("enabled = true") == 1


def test_unauthenticated_gh_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(GitHubConnectError, match="gh auth login"):
        connect_github(FakeRunner((CommandResult(1, "sensitive diagnostic"),)))

    assert not (tmp_path / ".stateback/secrets/github-token").exists()
    assert not load_project_config(tmp_path / "stateback.toml").github_enabled


def test_missing_gh_has_actionable_secret_free_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(GitHubConnectError, match="GitHub CLI was not found"):
        LocalCommandRunner().run(("gh", "auth", "status"))


@pytest.mark.parametrize(
    "results",
    [
        (
            CommandResult(0, ""),
            CommandResult(0, "not valid login!\n"),
        ),
        (
            CommandResult(0, ""),
            CommandResult(0, "octocat\n"),
            CommandResult(0, "line-one\nline-two\n"),
        ),
    ],
)
def test_malformed_gh_output_fails_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    results: tuple[CommandResult, ...],
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(GitHubConnectError, match="invalid"):
        connect_github(FakeRunner(results))

    assert not (tmp_path / ".stateback/secrets/github-token").exists()
    assert not load_project_config(tmp_path / "stateback.toml").github_enabled


def test_config_write_failure_restores_previous_credential_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    token = tmp_path / ".stateback/secrets/github-token"
    token.write_text("previous-secret\n")
    token.chmod(0o600)
    original_config = (tmp_path / "stateback.toml").read_bytes()
    failed = False

    def replace_with_failure(path: Path, content: bytes, *, mode: int) -> None:
        nonlocal failed
        if path.name == "stateback.toml" and not failed:
            failed = True
            raise OSError("simulated config failure")
        real_replace_file(path, content, mode=mode)

    monkeypatch.setattr("stateback.cli.connect.replace_file", replace_with_failure)
    with pytest.raises(OSError, match="simulated"):
        connect_github(_runner(token="new-secret"))

    assert token.read_text() == "previous-secret\n"
    assert (tmp_path / "stateback.toml").read_bytes() == original_config
