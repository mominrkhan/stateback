from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    AttemptState,
    EffectOutcome,
    OperationState,
    OutboxState,
    WorkCommand,
)
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.runtime import SynchronousRuntime
from tests.integration.runtime.conftest import (
    load_attempts,
    load_outbox,
    make_submit,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_timeout_after_send_routes_to_unknown_not_failed(
    runtime: SynchronousRuntime,
    adapter: object,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert len(attempts) == 1
    assert attempts[0].state is AttemptState.COMPLETED
    assert attempts[0].outcome is EffectOutcome.UNKNOWN
    outbox = [
        event
        for event in load_outbox(uow_factory)
        if event.aggregate_id == ids.operation_id
        and event.command is WorkCommand.VERIFY
    ]
    assert len(outbox) == 1
    assert outbox[0].state is OutboxState.PENDING


def test_applied_response_lost_routes_to_unknown_and_store_keeps_mutation(
    runtime: SynchronousRuntime,
    adapter: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
    assert store.get_by_resource_id("res-1") is not None


def test_malformed_after_accept_is_unknown(
    runtime: SynchronousRuntime,
    adapter: object,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_MALFORMED)
    ids = submit_ids(seq)
    result = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert result.operation is not None
    assert result.operation.state is OperationState.UNKNOWN
