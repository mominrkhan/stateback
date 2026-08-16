from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, PolicyVerdict
from stateback.policy import (
    PHASE5_POLICY_REVISION,
    PolicyEvaluation,
    ScriptedPolicyEngine,
)
from stateback.policy.evaluation import PHASE5_DEFAULT_OBLIGATIONS
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SynchronousRuntime
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import (
    load_operation,
    make_execute,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_provider_rejected_before_accept_fails_when_max_attempts_is_one(
    runtime: SynchronousRuntime,
    adapter: object,
    uow_factory: sessionmaker[Session],
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.disposition is RuntimeDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.FAILED
    assert store.all_resources() == ()
    assert load_operation(uow_factory, ids.operation_id).state is OperationState.FAILED


def test_provider_rejected_retries_when_policy_allows_two_attempts(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: object,
    clock: object,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, max_automatic_execution_attempts=2
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow_two",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)  # type: ignore[arg-type]
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    ids = submit_ids(seq)
    first = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert first.operation is not None
    assert first.operation.state is OperationState.READY
    second = runtime.execute(
        make_execute(seq, ids.operation_id, first.operation.version)
    )
    assert second.disposition is RuntimeDisposition.ACCEPTED
    assert second.operation is not None
    assert second.operation.state is OperationState.SUCCEEDED


def test_retryable_infrastructure_flag_does_not_retry_unknown(
    runtime: SynchronousRuntime,
    adapter: object,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
