from __future__ import annotations

import json
from pathlib import Path

import pytest
from nats.js.api import (
    DiscardPolicy,
    PersistMode,
    StoreCompression,
    StreamConsumerLimits,
)

from stateback.application.auth import Role
from stateback.deployment.config import (
    boolean_env,
    load_auth,
    load_policy,
    positive_int_env,
    read_secret_file,
)
from stateback.deployment.processes import (
    _consumer_config,
    _consumer_is_controlled,
    _quarantine_consumer_config,
    _quarantine_stream_config,
    _stream_config,
    _stream_is_controlled,
)
from stateback.domain.enums import (
    CompensationKind,
    IdempotencyMode,
    Mutability,
    PolicyVerdict,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.ids import OpaqueId
from stateback.policy.inputs import PolicyInputs
from stateback.providers.github import EFFECT_CREATE_ISSUE
from tests.unit.application.fixtures import IDENTITY

pytestmark = pytest.mark.unit


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_auth_configuration_builds_identity_and_approver_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "auth.json"
    _write(
        path,
        {
            "identities": [
                {
                    "token": "test-token",
                    "principal_type": "OPERATOR",
                    "principal_id": "operator-1",
                    "display_name": "Operator",
                    "roles": ["OPERATOR", "APPROVER"],
                }
            ]
        },
    )
    monkeypatch.setenv("STATEBACK_AUTH_CONFIG_FILE", str(path))
    authenticator, authorizer = load_auth()
    identity = authenticator.authenticate("test-token")
    assert identity.roles == frozenset({Role.OPERATOR, Role.APPROVER})
    assert (
        identity.principal.type,
        identity.principal.id,
    ) in authorizer.allowed_principals


def test_invalid_auth_configuration_does_not_echo_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "auth.json"
    _write(path, {"identities": [{"token": "must-not-escape"}]})
    monkeypatch.setenv("STATEBACK_AUTH_CONFIG_FILE", str(path))
    with pytest.raises(RuntimeError) as captured:
        load_auth()
    assert "must-not-escape" not in str(captured.value)


def test_policy_configuration_is_deterministic_and_default_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy.json"
    _write(
        path,
        {
            "revision": "release-policy-v1",
            "rules": [
                {
                    "rule_id": "github-approval",
                    "verdict": "REQUIRE_APPROVAL",
                    "providers": ["github"],
                }
            ],
        },
    )
    monkeypatch.setenv("STATEBACK_POLICY_CONFIG_FILE", str(path))
    policy = load_policy()
    allowed = policy.evaluate(
        PolicyInputs(
            operation_id=OpaqueId(value="00000000-0000-4000-8000-000000000001"),
            operation_version=1,
            intent_digest="0" * 64,
            effect=EFFECT_CREATE_ISSUE,
            risk_level=RiskLevel.MODERATE,
            mutability=Mutability.MUTATING,
            idempotency_mode=IdempotencyMode.NONE,
            verification_mode=VerificationMode.CUSTOM,
            compensation_kind=CompensationKind.MITIGATING,
            requester=IDENTITY.principal,
            metadata=(),
            deployment_environment="production",
        )
    )
    assert allowed.verdict is PolicyVerdict.REQUIRE_APPROVAL


def test_secret_file_and_integer_configuration_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "github-token"
    secret.write_text("ephemeral-test-token\n", encoding="utf-8")
    monkeypatch.setenv("STATEBACK_GITHUB_TOKEN_FILE", str(secret))
    assert read_secret_file("STATEBACK_GITHUB_TOKEN_FILE") == "ephemeral-test-token"

    monkeypatch.setenv("STATEBACK_WORKER_MAX_DELIVERIES", "0")
    with pytest.raises(RuntimeError, match="between"):
        positive_int_env("STATEBACK_WORKER_MAX_DELIVERIES", 5, maximum=100)


def test_boolean_configuration_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert boolean_env("STATEBACK_GITHUB_CONFIGURED") is False
    monkeypatch.setenv("STATEBACK_GITHUB_CONFIGURED", "1")
    assert boolean_env("STATEBACK_GITHUB_CONFIGURED") is True
    monkeypatch.setenv("STATEBACK_GITHUB_CONFIGURED", "true")
    with pytest.raises(RuntimeError, match="must be 0 or 1"):
        boolean_env("STATEBACK_GITHUB_CONFIGURED")


def test_configuration_files_are_bounded_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "oversize-secret"
    secret.write_bytes(b"x" * 4098)
    monkeypatch.setenv("STATEBACK_GITHUB_TOKEN_FILE", str(secret))
    with pytest.raises(RuntimeError, match="bounded"):
        read_secret_file("STATEBACK_GITHUB_TOKEN_FILE")

    auth = tmp_path / "oversize-auth.json"
    auth.write_bytes(b" " * (1024 * 1024 + 1))
    monkeypatch.setenv("STATEBACK_AUTH_CONFIG_FILE", str(auth))
    with pytest.raises(RuntimeError, match="supported size"):
        load_auth()


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("max_consumers", 2),
        ("max_msgs", 1),
        ("max_msgs_per_subject", 1),
        ("discard", DiscardPolicy.NEW),
        ("discard_new_per_subject", True),
        ("max_age", 1),
        ("max_bytes", 1),
        ("max_msg_size", 1),
        ("no_ack", True),
        ("duplicate_window", 1),
        ("sealed", True),
        ("deny_delete", False),
        ("deny_purge", False),
        ("allow_rollup_hdrs", True),
        ("allow_direct", True),
        ("mirror_direct", True),
        ("allow_msg_ttl", True),
        ("allow_msg_schedules", True),
        ("allow_atomic", True),
        ("allow_batched", True),
        ("first_seq", 99),
        ("compression", StoreCompression.S2),
        ("persist_mode", PersistMode.ASYNC),
        ("subject_delete_marker_ttl", 1),
        ("consumer_limits", StreamConsumerLimits(max_ack_pending=99)),
    ],
)
def test_stream_safety_validation_covers_destructive_retention_limits(
    field: str,
    unsafe_value: object,
) -> None:
    expected = _stream_config()
    actual = _stream_config()
    setattr(actual, field, unsafe_value)
    assert not _stream_is_controlled(actual, expected)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("ack_wait", 1),
        ("max_deliver", 99),
        ("filter_subject", "stateback.quarantine.v1"),
        ("max_waiting", 1),
        ("max_ack_pending", 99),
        ("headers_only", True),
        ("inactive_threshold", 1),
    ],
)
def test_consumer_safety_validation_rejects_delivery_drift(
    field: str,
    unsafe_value: object,
) -> None:
    expected = _consumer_config()
    actual = _consumer_config()
    setattr(actual, field, unsafe_value)
    assert not _consumer_is_controlled(actual, expected)


def test_quarantine_has_an_isolated_bounded_stream_and_operator_consumer() -> None:
    work = _stream_config()
    quarantine = _quarantine_stream_config()
    consumer = _quarantine_consumer_config()
    assert work.subjects == ["stateback.work.v1"]
    assert quarantine.name == "STATEBACK_QUARANTINE_V1"
    assert quarantine.subjects == ["stateback.quarantine.v1"]
    assert quarantine.max_consumers == 1
    assert quarantine.max_msgs == 10_000
    assert quarantine.max_bytes == 256 * 1024 * 1024
    assert consumer.durable_name == "stateback-quarantine-operator-v1"
    assert consumer.filter_subject == "stateback.quarantine.v1"
