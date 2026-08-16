from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    OperationState,
    OutboxState,
    PolicyVerdict,
    WorkCommand,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.policy import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
    PolicyEvaluation,
    ScriptedPolicyEngine,
)
from stateback.providers.reference.store import ReferenceStore
from stateback.runtime import SynchronousRuntime
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import (
    load_outbox,
    load_policies,
    make_submit,
    rebuild_runtime,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_submit_allow_reaches_ready_without_provider_mutation(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    result = runtime.submit(make_submit(seq, ids=ids))
    assert result.disposition is RuntimeDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.READY
    assert store.all_resources() == ()
    policies = load_policies(uow_factory, ids.operation_id)
    assert len(policies) == 1
    assert policies[0].verdict is PolicyVerdict.ALLOW
    outbox = [
        event
        for event in load_outbox(uow_factory)
        if event.aggregate_id == ids.operation_id
    ]
    assert len(outbox) == 1
    assert outbox[0].command is WorkCommand.EXECUTE
    assert outbox[0].state is OutboxState.PENDING


def test_submit_deny_reaches_denied_without_provider_mutation(
    uow_factory: sessionmaker[Session],
    registry: object,
    clock: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.DENY,
            reason_codes=("denied",),
            explanation=None,
            obligations=PHASE5_DEFAULT_OBLIGATIONS,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)  # type: ignore[arg-type]
    ids = submit_ids(seq)
    result = runtime.submit(make_submit(seq, ids=ids))
    assert result.disposition is RuntimeDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.DENIED
    assert store.all_resources() == ()


def test_submit_require_approval_does_not_execute(
    uow_factory: sessionmaker[Session],
    registry: object,
    clock: object,
    store: ReferenceStore,
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
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.disposition is RuntimeDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.AWAITING_APPROVAL
    assert store.all_resources() == ()


def test_submit_replay_same_ids_is_already_applied_then_skips_duplicate_policy(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    command = make_submit(seq, ids=ids)
    first = runtime.submit(command)
    assert first.operation is not None
    assert first.operation.state is OperationState.READY
    second = runtime.submit(command)
    assert second.disposition is RuntimeDisposition.ACCEPTED
    assert second.reason_code == "already_applied"
    assert second.operation is not None
    assert second.operation.state is OperationState.READY
    assert len(load_policies(uow_factory, ids.operation_id)) == 1


def test_submit_same_operation_id_different_digest_rejected(
    runtime: SynchronousRuntime,
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    first = runtime.submit(make_submit(seq, ids=ids))
    assert first.disposition is RuntimeDisposition.ACCEPTED
    second = runtime.submit(
        make_submit(
            seq,
            ids=ids,
            arguments=json_from_plain({"resource_id": "res-other"}),
        )
    )
    assert second.disposition is RuntimeDisposition.REJECTED
    assert second.reason_code == "intent_conflict"
