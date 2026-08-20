"""Fail-closed file and environment configuration for release processes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from stateback.application.auth import (
    AuthenticatedIdentity,
    Role,
    StaticTokenAuthenticator,
)
from stateback.approval.authorization import ConfiguredApproverAuthorizer
from stateback.domain.enums import PolicyVerdict, PrincipalType, RiskLevel
from stateback.domain.policy import PolicyObligations
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.policy.rules import PolicyRule, RulePolicyEngine


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityConfig(_StrictModel):
    token: str = Field(min_length=1, max_length=4096)
    principal_type: PrincipalType
    principal_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    roles: frozenset[Role] = Field(min_length=1)


class AuthConfig(_StrictModel):
    identities: tuple[IdentityConfig, ...] = Field(min_length=1, max_length=100)


class ObligationsConfig(_StrictModel):
    require_verification: bool = False
    max_automatic_execution_attempts: int | None = Field(default=1, ge=0, le=100)
    max_automatic_recovery_attempts: int | None = Field(default=None, ge=0, le=100)
    automatic_compensation_allowed: bool = False
    operator_reason_required: bool = True
    approval_expires_at: str | None = None

    def domain(self) -> PolicyObligations:
        return PolicyObligations(
            require_verification=self.require_verification,
            max_automatic_execution_attempts=self.max_automatic_execution_attempts,
            max_automatic_recovery_attempts=self.max_automatic_recovery_attempts,
            automatic_compensation_allowed=self.automatic_compensation_allowed,
            operator_reason_required=self.operator_reason_required,
            approval_expires_at=(
                None
                if self.approval_expires_at is None
                else UtcTimestamp.from_wire(
                    self.approval_expires_at,
                    field="PolicyConfig.approval_expires_at",
                )
            ),
        )


class RuleConfig(_StrictModel):
    rule_id: str = Field(min_length=1, max_length=200)
    verdict: PolicyVerdict
    explanation: str | None = Field(default=None, max_length=500)
    providers: frozenset[str] = frozenset()
    actions: frozenset[str] = frozenset()
    versions: frozenset[str] = frozenset()
    risk_levels: frozenset[RiskLevel] = frozenset()
    requester_types: frozenset[PrincipalType] = frozenset()
    deployment_environments: frozenset[str] = frozenset()
    obligations: ObligationsConfig = Field(default_factory=ObligationsConfig)


class PolicyConfig(_StrictModel):
    revision: str = Field(min_length=1, max_length=200)
    rules: tuple[RuleConfig, ...] = Field(max_length=500)
    default_obligations: ObligationsConfig = Field(default_factory=ObligationsConfig)


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value


def positive_int_env(name: str, default: int, *, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


def boolean_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise RuntimeError(f"{name} must be 0 or 1")


def _read_json(path: str, *, maximum_bytes: int = 1024 * 1024) -> object:
    config_path = Path(path)
    try:
        size = config_path.stat().st_size
        if size > maximum_bytes:
            raise RuntimeError("configuration file exceeds the supported size")
        return json.loads(config_path.read_text(encoding="utf-8"))
    except RuntimeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("configuration file is unreadable or invalid") from exc


def load_auth() -> tuple[StaticTokenAuthenticator, ConfiguredApproverAuthorizer]:
    try:
        config = AuthConfig.model_validate(
            _read_json(required_env("STATEBACK_AUTH_CONFIG_FILE"))
        )
    except ValidationError:
        raise RuntimeError("authentication configuration is invalid") from None
    identities: dict[str, AuthenticatedIdentity] = {}
    approvers: set[tuple[PrincipalType, str]] = set()
    for item in config.identities:
        if item.token in identities:
            raise RuntimeError("authentication tokens must be unique")
        principal = PrincipalRef(
            type=item.principal_type,
            id=item.principal_id,
            display_name=item.display_name,
        )
        identities[item.token] = AuthenticatedIdentity(
            principal=principal, roles=item.roles
        )
        if Role.APPROVER in item.roles:
            approvers.add((principal.type, principal.id))
    return (
        StaticTokenAuthenticator(identities_by_token=identities),
        ConfiguredApproverAuthorizer(allowed_principals=frozenset(approvers)),
    )


def load_policy() -> RulePolicyEngine:
    try:
        config = PolicyConfig.model_validate(
            _read_json(required_env("STATEBACK_POLICY_CONFIG_FILE"))
        )
    except ValidationError:
        raise RuntimeError("policy configuration is invalid") from None
    return RulePolicyEngine(
        policy_revision=config.revision,
        rules=tuple(
            PolicyRule(
                rule_id=rule.rule_id,
                verdict=rule.verdict,
                obligations=rule.obligations.domain(),
                explanation=rule.explanation,
                providers=rule.providers,
                actions=rule.actions,
                versions=rule.versions,
                risk_levels=rule.risk_levels,
                requester_types=rule.requester_types,
                deployment_environments=rule.deployment_environments,
            )
            for rule in config.rules
        ),
        default_obligations=config.default_obligations.domain(),
    )


def read_secret_file(name: str) -> str | None:
    path = os.environ.get(name)
    if path is None:
        return None
    try:
        secret_path = Path(path)
        if secret_path.stat().st_size > 4097:
            raise RuntimeError(f"{name} must contain one bounded non-empty secret")
        value = secret_path.read_text(encoding="utf-8").strip()
    except RuntimeError:
        raise
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"{name} cannot be read") from exc
    if not value or len(value) > 4096 or "\n" in value:
        raise RuntimeError(f"{name} must contain one bounded non-empty secret")
    return value
