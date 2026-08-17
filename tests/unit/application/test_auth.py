from __future__ import annotations

import pytest

from stateback.application.auth import (
    AuthenticationError,
    Role,
    StaticTokenAuthenticator,
)
from tests.unit.application.fixtures import IDENTITY

pytestmark = pytest.mark.unit


def test_static_authenticator_fails_closed() -> None:
    authenticator = StaticTokenAuthenticator(
        identities_by_token={"safe-token": IDENTITY}
    )
    with pytest.raises(AuthenticationError, match="missing_credentials"):
        authenticator.authenticate(None)
    with pytest.raises(AuthenticationError, match="invalid_credentials"):
        authenticator.authenticate("wrong")


def test_authenticated_identity_requires_server_role() -> None:
    IDENTITY.require(Role.CALLER)
    with pytest.raises(Exception, match="insufficient_role"):
        IDENTITY.require(Role.OPERATOR)
