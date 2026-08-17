from __future__ import annotations

import pytest

from stateback.domain.enums import VerificationTarget
from stateback.recovery.request import build_original_verification_request
from tests.unit.domain.fixtures import TS, VERIFY_ID
from tests.unit.recovery.fixtures import make_attempt, make_operation

pytestmark = pytest.mark.unit


def test_request_target_is_original_effect() -> None:
    request = build_original_verification_request(
        operation=make_operation(version=3),
        attempt=make_attempt(),
        verification_id=VERIFY_ID,
        requested_at=TS,
    )
    assert request.target is VerificationTarget.ORIGINAL_EFFECT


def test_request_version_is_pre_transition_operation_version() -> None:
    operation = make_operation(version=4)
    request = build_original_verification_request(
        operation=operation,
        attempt=make_attempt(),
        verification_id=VERIFY_ID,
        requested_at=TS,
    )
    assert request.operation_version == 4
    assert request.operation_version == operation.version


def test_request_copies_attempt_external_ids() -> None:
    attempt = make_attempt(
        external_operation_id="ext-op-1",
        external_resource_ids=("res-1",),
    )
    request = build_original_verification_request(
        operation=make_operation(),
        attempt=attempt,
        verification_id=VERIFY_ID,
        requested_at=TS,
    )
    assert request.external_operation_id == "ext-op-1"
    assert request.external_resource_ids == ("res-1",)
    assert request.target_attempt_id == attempt.attempt_id


def test_request_without_attempt_has_empty_external_ids() -> None:
    request = build_original_verification_request(
        operation=make_operation(),
        attempt=None,
        verification_id=VERIFY_ID,
        requested_at=TS,
    )
    assert request.external_operation_id is None
    assert request.external_resource_ids == ()
    assert request.target_attempt_id is None
