from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.persistence.uow import unit_of_work
from stateback.runtime import SynchronousRuntime
from stateback.runtime.results import RuntimeDisposition
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import IdSeq, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_secret_in_metadata_never_reaches_journal(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    result = runtime.submit(
        make_submit(seq, ids=ids, metadata=(("authorization", "bearer abc"),))
    )
    assert result.disposition is RuntimeDisposition.REJECTED
    assert result.reason_code == "secret_field"
    with unit_of_work(uow_factory) as uow:
        assert uow.operations.get(ids.operation_id) is None
        assert uow.policy_decisions.list_for_operation(ids.operation_id) == []
        assert uow.audit_events.list_for_operation(ids.operation_id) == []
