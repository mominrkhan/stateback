"""Deployment-owned authentication and Stateback role authorization."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from stateback.domain.refs import PrincipalRef


class Role(StrEnum):
    CALLER = "CALLER"
    READER = "READER"
    OPERATOR = "OPERATOR"
    APPROVER = "APPROVER"


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticatedIdentity:
    principal: PrincipalRef
    roles: frozenset[Role]

    def require(self, *allowed: Role) -> None:
        if not self.roles.intersection(allowed):
            raise AuthorizationError("insufficient_role")


class AuthenticationError(Exception):
    """Safe authentication failure without credential material."""


class AuthenticationUnavailableError(Exception):
    """Deployment authenticator failed without exposing its diagnostics."""


class AuthorizationError(Exception):
    """Safe authorization failure."""


@runtime_checkable
class Authenticator(Protocol):
    def authenticate(self, credential: str | None) -> AuthenticatedIdentity: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class StaticTokenAuthenticator:
    """Explicit local/self-hosted authenticator; no default tokens or bypass."""

    identities_by_token: Mapping[str, AuthenticatedIdentity]

    def __post_init__(self) -> None:
        if not self.identities_by_token:
            raise ValueError("at least one configured token is required")
        if any(not token for token in self.identities_by_token):
            raise ValueError("configured tokens must be non-empty")
        object.__setattr__(
            self,
            "identities_by_token",
            MappingProxyType(dict(self.identities_by_token)),
        )

    def authenticate(self, credential: str | None) -> AuthenticatedIdentity:
        if credential is None:
            raise AuthenticationError("missing_credentials")
        match: AuthenticatedIdentity | None = None
        for token, identity in self.identities_by_token.items():
            if hmac.compare_digest(credential, token):
                match = identity
        if match is None:
            raise AuthenticationError("invalid_credentials")
        return match
