from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, PolicyVerdict
from stateback.policy import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
    PolicyEvaluation,
    ScriptedPolicyEngine,
)
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.registry import CapabilityRegistry
from stateback.runtime import SimulatedCrash, SynchronousRuntime
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import (
    load_operation,
    make_execute,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_execute_on_succeeded_does_not_call_provider_again(
    runtime: SynchronousRuntime,
    adapter: object,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    ids = submit_ids(seq)
    first = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert first.operation is not None
    assert first.operation.state is OperationState.SUCCEEDED
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    second = runtime.execute(
        make_execute(seq, ids.operation_id, first.operation.version)
    )
    assert second.disposition is RuntimeDisposition.ACCEPTED
    assert second.reason_code == "already_applied"
    assert adapter._execute_scripts == [ReferenceExecuteScript.NOT_APPLIED_REJECTED]


def test_execute_on_executing_started_is_in_flight(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    seq: IdSeq,
) -> None:
    runtime = rebuild_runtime(
        uow_factory,
        registry,
        clock,  # type: ignore[arg-type]
        crash_after=RuntimeCrashPoint.AFTER_CLAIM_COMMIT,
    )
    ids = submit_ids(seq)
    exec_ids = execute_ids(seq)
    with pytest.raises(SimulatedCrash):
        runtime.run(make_submit(seq, ids=ids), exec_ids)
    op = load_operation(uow_factory, ids.operation_id)
    result = runtime.execute(make_execute(seq, ids.operation_id, op.version))
    assert result.disposition is RuntimeDisposition.IN_FLIGHT
    assert result.reason_code == "in_flight"


def test_execute_on_unknown_is_rejected(
    runtime: SynchronousRuntime,
    adapter: object,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    first = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert first.operation is not None
    assert first.operation.state is OperationState.UNKNOWN
    second = runtime.execute(
        make_execute(seq, ids.operation_id, first.operation.version)
    )
    assert second.disposition is RuntimeDisposition.REJECTED
    assert second.reason_code == "unsupported_state"


def test_execute_on_awaiting_approval_is_not_ready(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    clock: object,
    seq: IdSeq,
) -> None:
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.REQUIRE_APPROVAL,
            reason_codes=("need_approval",),
            explanation=None,
            obligations=PHASE5_DEFAULT_OBLIGATIONS,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)  # type: ignore[arg-type]
    ids = submit_ids(seq)
    submitted = runtime.submit(make_submit(seq, ids=ids))
    assert submitted.operation is not None
    assert submitted.operation.state is OperationState.AWAITING_APPROVAL
    result = runtime.execute(
        make_execute(seq, ids.operation_id, submitted.operation.version)
    )
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "not_ready"
