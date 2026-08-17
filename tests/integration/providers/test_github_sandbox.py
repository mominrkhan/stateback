from __future__ import annotations

import os

import pytest

from stateback.domain.capability import (
    CompensationRequest,
    ProviderExecutionContext,
    ProviderExecutionRequest,
)
from stateback.domain.enums import EffectOutcome
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.providers.github import EFFECT_CREATE_ISSUE, GitHubAdapter
from stateback.providers.reference.clock import FixedClock
from tests.unit.domain.fixtures import TS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.github_sandbox,
]


def test_create_and_mitigate_issue_in_explicit_sandbox() -> None:
    if os.environ.get("STATEBACK_RUN_GITHUB_SANDBOX") != "1":
        pytest.skip("set STATEBACK_RUN_GITHUB_SANDBOX=1 for the live sandbox test")
    if os.environ.get("STATEBACK_GITHUB_SANDBOX_CONFIRM_MUTATION") != "1":
        pytest.skip("explicit sandbox mutation confirmation is required")
    token = os.environ["STATEBACK_GITHUB_TOKEN"]
    owner = os.environ["STATEBACK_GITHUB_SANDBOX_OWNER"]
    repo = os.environ["STATEBACK_GITHUB_SANDBOX_REPO"]
    operation_id = OpaqueId(value="00000000-0000-4000-8000-00000000b001")
    attempt_id = OpaqueId(value="00000000-0000-4000-8000-00000000b002")
    context = ProviderExecutionContext(
        operation_id=operation_id,
        attempt_id=attempt_id,
        idempotency_identity=f"sb:v1:op:{operation_id.value}",
        provider_idempotency_key=None,
        correlation_id="github-sandbox",
        deadline=None,
    )
    adapter = GitHubAdapter.from_token(token=token, clock=FixedClock(TS))
    execution = adapter.execute(
        context,
        ProviderExecutionRequest(
            effect=EFFECT_CREATE_ISSUE,
            arguments=json_from_plain(
                {
                    "owner": owner,
                    "repo": repo,
                    "title": "Stateback sandbox verification",
                    "body": "This issue is created and closed by an opt-in test.",
                }
            ),
        ),
    )
    assert execution.outcome is EffectOutcome.APPLIED
    assert execution.evidence is not None
    compensation = adapter.compensate(
        context,
        CompensationRequest(
            original_operation_id=operation_id,
            compensation_id=OpaqueId(value="00000000-0000-4000-8000-00000000b003"),
            compensation_attempt_id=OpaqueId(
                value="00000000-0000-4000-8000-00000000b004"
            ),
            original_evidence=(execution.evidence,),
            compensation_arguments=json_from_plain({}),
            idempotency_identity="sb:v1:comp:github-sandbox",
            provider_idempotency_key=None,
        ),
    )
    assert compensation.outcome is EffectOutcome.APPLIED
