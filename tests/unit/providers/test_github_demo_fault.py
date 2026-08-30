from __future__ import annotations

import json
from pathlib import Path

import pytest

from stateback.domain.capability import (
    ProviderExecutionContext,
    ProviderExecutionRequest,
)
from stateback.domain.enums import EffectOutcome
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.providers.github import (
    EFFECT_CREATE_ISSUE,
    GitHubAdapter,
    GitHubHttpResponse,
)
from stateback.providers.github.demo_fault import OperationScopedLostResponseAdapter
from stateback.providers.reference.clock import FixedClock
from tests.unit.domain.fixtures import TS

pytestmark = pytest.mark.unit

OPERATION_ID = OpaqueId(value="00000000-0000-4000-8000-00000000d001")


class CountingTransport:
    def __init__(self, *, status: int = 201) -> None:
        self.count = 0
        self.status = status

    def request(
        self, *, method: str, path: str, body: bytes | None, timeout_seconds: float
    ) -> GitHubHttpResponse:
        del method, path, body, timeout_seconds
        self.count += 1
        return GitHubHttpResponse(
            status=self.status,
            headers=(),
            body=json.dumps(
                {
                    "id": 1,
                    "number": self.count,
                    "html_url": f"https://github.com/acme/sandbox/issues/{self.count}",
                    "repository_url": "https://api.github.com/repos/acme/sandbox",
                    "state": "open",
                    "body": "marker",
                }
            ).encode(),
        )


def context(operation_id: OpaqueId = OPERATION_ID) -> ProviderExecutionContext:
    return ProviderExecutionContext(
        operation_id=operation_id,
        attempt_id=OpaqueId(value="00000000-0000-4000-8000-00000000d002"),
        idempotency_identity="demo",
        provider_idempotency_key=None,
        correlation_id=None,
        deadline=None,
    )


def request() -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        effect=EFFECT_CREATE_ISSUE,
        arguments=json_from_plain(
            {"owner": "acme", "repo": "sandbox", "title": "demo"}
        ),
    )


def wrapped(
    path: Path, transport: CountingTransport
) -> OperationScopedLostResponseAdapter:
    clock = FixedClock(TS)
    return OperationScopedLostResponseAdapter(
        delegate=GitHubAdapter(transport=transport, clock=clock),
        arm_directory=path,
        clock=clock,
    )


def test_exact_operation_fault_is_consumed_after_one_success(tmp_path: Path) -> None:
    transport = CountingTransport()
    (tmp_path / OPERATION_ID.value).write_text("armed\n")
    adapter = wrapped(tmp_path, transport)
    result = adapter.execute(context(), request())
    assert transport.count == 1
    assert result.outcome is EffectOutcome.UNKNOWN
    assert result.external_resource_ids == ()
    assert not (tmp_path / OPERATION_ID.value).exists()

    second = adapter.execute(context(), request())
    assert transport.count == 2
    assert second.outcome is EffectOutcome.APPLIED


def test_wrong_operation_is_not_faulted_or_consumed(tmp_path: Path) -> None:
    transport = CountingTransport()
    (tmp_path / OPERATION_ID.value).write_text("armed\n")
    other = OpaqueId(value="00000000-0000-4000-8000-00000000d099")
    result = wrapped(tmp_path, transport).execute(context(other), request())
    assert result.outcome is EffectOutcome.APPLIED
    assert (tmp_path / OPERATION_ID.value).is_file()


def test_symlink_arm_is_never_consumed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("armed\n")
    (tmp_path / OPERATION_ID.value).symlink_to(target)
    result = wrapped(tmp_path, CountingTransport()).execute(context(), request())
    assert result.outcome is EffectOutcome.APPLIED
    assert target.read_text() == "armed\n"


def test_unarmed_operation_is_never_faulted(tmp_path: Path) -> None:
    transport = CountingTransport()

    result = wrapped(tmp_path, transport).execute(context(), request())

    assert transport.count == 1
    assert result.outcome is EffectOutcome.APPLIED


def test_provider_rejection_before_mutation_does_not_consume_arm(
    tmp_path: Path,
) -> None:
    marker = tmp_path / OPERATION_ID.value
    marker.write_text("armed\n")
    transport = CountingTransport(status=422)

    result = wrapped(tmp_path, transport).execute(context(), request())

    assert transport.count == 1
    assert result.outcome is EffectOutcome.NOT_APPLIED
    assert marker.is_file()
