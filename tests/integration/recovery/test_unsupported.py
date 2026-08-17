from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.effects import EFFECT_MUTATE_NONE
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import load_audits, make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_mutate_none_unknown_escalates_without_verify(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    ids = submit_ids(seq)
    executed = runtime.run(
        make_submit(seq, ids=ids, effect=EFFECT_MUTATE_NONE),
        execute_ids(seq),
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.UNKNOWN
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.MANUAL_INTERVENTION
    assert recovered.reason_code == "accepted"
    assert recovered.transition is not None
    audits = load_audits(uow_factory, ids.operation_id)
    assert any(event.reason_code == "unknown_without_verification" for event in audits)
    assert adapter._verify_scripts == [ReferenceVerifyScript.UNKNOWN_INCONSISTENT]
