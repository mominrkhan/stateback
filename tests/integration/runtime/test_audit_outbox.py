from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OutboxState, WorkCommand
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.runtime import SynchronousRuntime
from tests.integration.runtime.conftest import (
    load_audits,
    load_outbox,
    make_submit,
)
from tests.integration.runtime.idseq import IdSeq, execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_policy_allow_writes_pending_execute_outbox_not_published(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    runtime.submit(make_submit(seq, ids=ids))
    matching = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == ids.allow_outbox_event_id
    ]
    assert len(matching) == 1
    assert matching[0].command is WorkCommand.EXECUTE
    assert matching[0].state is OutboxState.PENDING
    assert matching[0].published_at is None


def test_execution_unknown_writes_pending_verify_outbox_not_published(
    runtime: SynchronousRuntime,
    adapter: object,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    from stateback.providers.reference.adapter import ReferenceAdapter

    assert isinstance(adapter, ReferenceAdapter)
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    exec_ids = execute_ids(seq)
    runtime.run(make_submit(seq, ids=ids), exec_ids)
    matching = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == exec_ids.execution_outbox_event_id
    ]
    assert len(matching) == 1
    assert matching[0].command is WorkCommand.VERIFY
    assert matching[0].state is OutboxState.PENDING
    assert matching[0].published_at is None


def test_succeeded_has_no_verify_outbox(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    exec_ids = execute_ids(seq)
    runtime.run(make_submit(seq, ids=ids), exec_ids)
    verify = [
        event
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.VERIFY
    ]
    assert verify == []
    unused = [
        event
        for event in load_outbox(uow_factory)
        if event.event_id == exec_ids.execution_outbox_event_id
    ]
    assert unused == []


def test_audit_sequence_is_append_only_across_submit_and_execute(
    runtime: SynchronousRuntime,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    ids = submit_ids(seq)
    runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    audits = load_audits(uow_factory, ids.operation_id)
    sequences = [event.sequence for event in audits]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(sequences) >= 4
