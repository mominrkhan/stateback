"""Strict local-project configuration with no secret values."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ProjectConfigError(ValueError):
    """A local project configuration is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class DevConfig:
    api_host: str = "127.0.0.1"
    api_port: int = 8080
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    nats_host: str = "127.0.0.1"
    nats_port: int = 4222
    nats_monitor_port: int = 8222


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    policy: Path
    auth: Path
    github_token: Path


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    root: Path
    name: str
    dev: DevConfig
    paths: ProjectPaths
    github_enabled: bool


def _table(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ProjectConfigError(f"{name} must be a TOML table")
    return value


def _only(table: dict[str, object], allowed: set[str], name: str) -> None:
    unexpected = sorted(set(table) - allowed)
    if unexpected:
        raise ProjectConfigError(
            f"{name} contains unsupported keys: {', '.join(unexpected)}"
        )


def _port(table: dict[str, object], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ProjectConfigError(f"dev.{key} must be an integer between 1 and 65535")
    return value


def _host(table: dict[str, object], key: str) -> str:
    value = table.get(key, "127.0.0.1")
    if value != "127.0.0.1":
        raise ProjectConfigError(f"dev.{key} must be 127.0.0.1")
    return value


def _project_path(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ProjectConfigError(f"paths.{field} must be a relative project path")
    resolved = (root / value).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ProjectConfigError(f"paths.{field} must remain inside the project")
    return resolved


def load_project_config(path: Path) -> ProjectConfig:
    if path.is_symlink() or not path.is_file():
        raise ProjectConfigError("stateback.toml must be a regular file")
    try:
        if path.stat().st_size > 64 * 1024:
            raise ProjectConfigError("stateback.toml exceeds the supported size")
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except ProjectConfigError:
        raise
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectConfigError("stateback.toml is unreadable or invalid") from exc

    _only(raw, {"schema_version", "project", "dev", "paths", "providers"}, "root")
    if raw.get("schema_version") != 1:
        raise ProjectConfigError("schema_version must be 1")
    project = _table(raw.get("project"), "project")
    _only(project, {"name"}, "project")
    name = project.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise ProjectConfigError(
            "project.name must be a non-empty string up to 100 characters"
        )

    dev = _table(raw.get("dev", {}), "dev")
    _only(
        dev,
        {
            "api_host",
            "api_port",
            "postgres_host",
            "postgres_port",
            "nats_host",
            "nats_port",
            "nats_monitor_port",
        },
        "dev",
    )
    paths = _table(raw.get("paths", {}), "paths")
    _only(paths, {"policy", "auth"}, "paths")
    providers = _table(raw.get("providers", {}), "providers")
    _only(providers, {"github"}, "providers")
    github = _table(providers.get("github", {}), "providers.github")
    _only(github, {"enabled", "token_file"}, "providers.github")
    enabled = github.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProjectConfigError("providers.github.enabled must be a boolean")

    root = path.parent.resolve()
    configured = DevConfig(
        api_host=_host(dev, "api_host"),
        api_port=_port(dev, "api_port", 8080),
        postgres_host=_host(dev, "postgres_host"),
        postgres_port=_port(dev, "postgres_port", 5432),
        nats_host=_host(dev, "nats_host"),
        nats_port=_port(dev, "nats_port", 4222),
        nats_monitor_port=_port(dev, "nats_monitor_port", 8222),
    )
    ports = (
        configured.api_port,
        configured.postgres_port,
        configured.nats_port,
        configured.nats_monitor_port,
    )
    if len(set(ports)) != len(ports):
        raise ProjectConfigError("dev ports must be distinct")
    return ProjectConfig(
        root=root,
        name=name,
        dev=configured,
        paths=ProjectPaths(
            policy=_project_path(
                root, paths.get("policy", "stateback.policy.json"), "policy"
            ),
            auth=_project_path(root, paths.get("auth", ".stateback/auth.json"), "auth"),
            github_token=_project_path(
                root,
                github.get("token_file", ".stateback/secrets/github-token"),
                "providers.github.token_file",
            ),
        ),
        github_enabled=enabled,
    )
