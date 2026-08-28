"""Secure first-use provider connection commands."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stateback.cli.config import ProjectConfig, load_project_config
from stateback.cli.project import find_project_root, replace_file


class GitHubConnectError(RuntimeError):
    """GitHub could not be connected without exposing credential material."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...


class LocalCommandRunner:
    def run(self, arguments: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=20,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitHubConnectError(
                "GitHub CLI was not found.\n\n"
                "Install `gh`, authenticate with:\n  gh auth login\n\n"
                "Then retry:\n  stateback connect github"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitHubConnectError(
                "GitHub CLI did not respond.\n\n"
                "Check `gh auth status`, then retry:\n  stateback connect github"
            ) from exc
        return CommandResult(completed.returncode, completed.stdout)


@dataclass(frozen=True, slots=True)
class GitHubConnection:
    account: str


_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_GITHUB_SECTION = re.compile(r"(?m)^\[providers\.github\][ \t]*$")
_NEXT_SECTION = re.compile(r"(?m)^\[")
_ENABLED = re.compile(r"(?m)^enabled[ \t]*=[^\n]*$")


def _single_line(value: str, *, label: str, maximum: int) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > maximum
        or any(char.isspace() for char in stripped)
    ):
        raise GitHubConnectError(f"GitHub CLI returned an invalid {label}")
    return stripped


def _github_credentials(runner: CommandRunner) -> tuple[str, str]:
    if runner.run(("gh", "auth", "status", "--hostname", "github.com")).returncode != 0:
        raise GitHubConnectError(
            "GitHub CLI is not authenticated.\n\n"
            "Run:\n  gh auth login\n\n"
            "Then retry:\n  stateback connect github"
        )
    identity = runner.run(
        ("gh", "api", "--hostname", "github.com", "user", "--jq", ".login")
    )
    if identity.returncode != 0:
        raise GitHubConnectError(
            "GitHub identity could not be verified.\n\n"
            "Check `gh auth status`, then retry:\n  stateback connect github"
        )
    account = _single_line(identity.stdout, label="account", maximum=39)
    if _LOGIN.fullmatch(account) is None:
        raise GitHubConnectError("GitHub CLI returned an invalid account")
    credential = runner.run(("gh", "auth", "token", "--hostname", "github.com"))
    if credential.returncode != 0:
        raise GitHubConnectError(
            "GitHub CLI could not provide its credential.\n\n"
            "Run `gh auth refresh`, then retry:\n  stateback connect github"
        )
    token = _single_line(credential.stdout, label="credential", maximum=4096)
    return account, token


def _enable_github(content: str) -> str:
    section = _GITHUB_SECTION.search(content)
    if section is None:
        separator = "" if content.endswith("\n\n") else "\n"
        return (
            f"{content.rstrip()}\n{separator}[providers.github]\n"
            "enabled = true\n"
            'token_file = ".stateback/secrets/github-token"\n'
        )
    next_section = _NEXT_SECTION.search(content, section.end())
    end = len(content) if next_section is None else next_section.start()
    body = content[section.end() : end]
    if _ENABLED.search(body) is not None:
        body = _ENABLED.sub("enabled = true", body, count=1)
    else:
        body = "\nenabled = true" + body
    return content[: section.end()] + body + content[end:]


def _safe_existing_token(path: Path) -> bytes | None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GitHubConnectError(f"refusing unsafe GitHub credential file: {path}")
    if not path.exists():
        return None
    try:
        if path.stat().st_size > 4097:
            raise GitHubConnectError("existing GitHub credential file is too large")
        return path.read_bytes()
    except OSError as exc:
        raise GitHubConnectError(
            "existing GitHub credential file cannot be read"
        ) from exc


def _write_connection(config: ProjectConfig, token: str) -> None:
    config_path = config.root / "stateback.toml"
    original_config = config_path.read_bytes()
    original_token = _safe_existing_token(config.paths.github_token)
    try:
        config_text = original_config.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubConnectError("stateback.toml is not valid UTF-8") from exc
    enabled_config = _enable_github(config_text).encode()
    config.paths.github_token.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        replace_file(config.paths.github_token, f"{token}\n".encode(), mode=0o600)
        replace_file(config_path, enabled_config, mode=0o644)
        loaded = load_project_config(config_path)
        if not loaded.github_enabled:
            raise GitHubConnectError("GitHub provider could not be enabled")
    except Exception:
        try:
            replace_file(config_path, original_config, mode=0o644)
            if original_token is None:
                config.paths.github_token.unlink(missing_ok=True)
            else:
                replace_file(config.paths.github_token, original_token, mode=0o600)
        except OSError:
            pass
        raise
    if os.name == "posix" and (config.paths.github_token.stat().st_mode & 0o077):
        raise GitHubConnectError("GitHub credential file permissions are unsafe")


def connect_github(runner: CommandRunner | None = None) -> GitHubConnection:
    root = find_project_root(Path.cwd())
    config = load_project_config(root / "stateback.toml")
    account, token = _github_credentials(runner or LocalCommandRunner())
    _write_connection(config, token)
    return GitHubConnection(account=account)
