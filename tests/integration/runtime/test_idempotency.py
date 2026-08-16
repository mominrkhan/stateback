from __future__ import annotations

import pytest

from stateback.domain.enums import OperationState
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.runtime import SynchronousRuntime
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import make_execute, make_submit
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_second_execute_same_provider_key_replays_applied_without_second_store_row(
    runtime: SynchronousRuntime,
    adapter: object,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    ids = submit_ids(seq)
    first = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert first.operation is not None
    assert first.operation.state is OperationState.SUCCEEDED
    assert len(store.all_resources()) == 1
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    second = runtime.execute(
        make_execute(seq, ids.operation_id, first.operation.version)
    )
    assert second.disposition is RuntimeDisposition.ACCEPTED
    assert second.reason_code == "already_applied"
    assert len(store.all_resources()) == 1
    assert adapter._execute_scripts == [ReferenceExecuteScript.NOT_APPLIED_REJECTED]
