"""Idempotent local Stateback project initialization."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from stateback.cli.config import ProjectConfigError, load_project_config
from stateback.cli.project import create_file, ensure_private_directory
from stateback.deployment.config import AuthConfig, PolicyConfig


@dataclass(frozen=True, slots=True)
class InitResult:
    project_root: Path
    created: tuple[str, ...]
    existing: tuple[str, ...]

    @property
    def status(self) -> str:
        return "initialized" if self.created else "already_initialized"

    def to_wire(self) -> dict[str, object]:
        return {
            "status": self.status,
            "project_root": str(self.project_root),
            "created": list(self.created),
            "existing": list(self.existing),
        }


def _toml(project_name: str) -> bytes:
    quoted_name = json.dumps(project_name)
    return f"""schema_version = 1

[project]
name = {quoted_name}

[dev]
api_host = "127.0.0.1"
api_port = 8080
postgres_host = "127.0.0.1"
postgres_port = 5432
nats_host = "127.0.0.1"
nats_port = 4222
nats_monitor_port = 8222

[paths]
policy = "stateback.policy.json"
auth = ".stateback/auth.json"

[providers.github]
enabled = false
token_file = ".stateback/secrets/github-token"
""".encode()


def _policy() -> bytes:
    value = {
        "revision": "local-development-v1",
        "rules": [
            {
                "rule_id": "github-create-issue-requires-approval",
                "verdict": "REQUIRE_APPROVAL",
                "providers": ["github"],
                "actions": ["create_issue"],
                "versions": ["v1"],
                "obligations": {
                    "require_verification": False,
                    "max_automatic_execution_attempts": 1,
                    "max_automatic_recovery_attempts": 3,
                    "automatic_compensation_allowed": False,
                    "operator_reason_required": True,
                    "approval_expires_at": None,
                },
            }
        ],
    }
    return (json.dumps(value, indent=2) + "\n").encode()


def _auth() -> bytes:
    agent_token = secrets.token_urlsafe(32)
    operator_token = secrets.token_urlsafe(32)
    while operator_token == agent_token:
        operator_token = secrets.token_urlsafe(32)
    value = {
        "identities": [
            {
                "token": agent_token,
                "principal_type": "AGENT",
                "principal_id": "local-agent",
                "display_name": "Local agent",
                "roles": ["CALLER", "READER"],
            },
            {
                "token": operator_token,
                "principal_type": "OPERATOR",
                "principal_id": "local-operator",
                "display_name": "Local operator",
                "roles": ["OPERATOR", "APPROVER"],
            },
        ]
    }
    return (json.dumps(value, indent=2) + "\n").encode()


def _validate_json(path: Path, model: type[AuthConfig] | type[PolicyConfig]) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ProjectConfigError(f"{path.name} must be a bounded regular file")
    try:
        validated = model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise ProjectConfigError(f"existing {path.name} is invalid") from exc
    if isinstance(validated, AuthConfig):
        tokens = [identity.token for identity in validated.identities]
        if len(tokens) != len(set(tokens)):
            raise ProjectConfigError("existing auth.json contains duplicate tokens")


def initialize(root: Path) -> InitResult:
    root = root.resolve()
    if not root.is_dir():
        raise ProjectConfigError("project root must be an existing directory")
    state_dir = root / ".stateback"
    ensure_private_directory(state_dir)
    for directory in (state_dir / "secrets", state_dir / "run", state_dir / "logs"):
        ensure_private_directory(directory)

    config_path = root / "stateback.toml"
    policy_path = root / "stateback.policy.json"
    auth_path = state_dir / "auth.json"
    if config_path.exists() or config_path.is_symlink():
        load_project_config(config_path)
    if policy_path.exists() or policy_path.is_symlink():
        _validate_json(policy_path, PolicyConfig)
    if auth_path.exists() or auth_path.is_symlink():
        _validate_json(auth_path, AuthConfig)

    candidates = (
        (config_path, _toml(root.name or "stateback-project"), 0o644),
        (policy_path, _policy(), 0o644),
        (state_dir / ".gitignore", b"*\n!.gitignore\n", 0o644),
        (auth_path, _auth(), 0o600),
    )
    created: list[str] = []
    existing: list[str] = []
    for path, content, mode in candidates:
        relative = path.relative_to(root).as_posix()
        (created if create_file(path, content, mode=mode) else existing).append(
            relative
        )

    load_project_config(config_path)
    _validate_json(policy_path, PolicyConfig)
    _validate_json(auth_path, AuthConfig)
    return InitResult(root, tuple(created), tuple(existing))
