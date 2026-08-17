from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import EffectOutcome, OperationState, WorkCommand
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import ReferenceVerifyScript
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import (
    load_verifications,
    make_recovery,
    run_unknown_timeout,
)
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import load_outbox

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_verify_inconclusive_returns_to_unknown(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONCLUSIVE)
    op = run_unknown_timeout(runtime, seq)
    before = [
        event.event_id
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.EXECUTE
        and event.aggregate_id == op.operation_id
    ]
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.UNKNOWN
    rows = load_verifications(uow_factory, op.operation_id)
    assert len(rows) == 1
    request, result = rows[0]
    del request
    assert result is not None
    assert result.outcome is EffectOutcome.UNKNOWN
    after = [
        event.event_id
        for event in load_outbox(uow_factory)
        if event.command is WorkCommand.EXECUTE
        and event.aggregate_id == op.operation_id
    ]
    assert after == before


def test_third_inconclusive_escalates_to_manual(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    op = run_unknown_timeout(runtime, seq)
    current = op
    for _ in range(3):
        adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONCLUSIVE)
        recovered = recovery.recover(
            make_recovery(seq, current.operation_id, current.version)
        )
        assert recovered.operation is not None
        current = recovered.operation
    assert current.state is OperationState.MANUAL_INTERVENTION
