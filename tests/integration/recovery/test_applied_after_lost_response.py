from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import (
    AttemptState,
    AuditEventType,
    EffectOutcome,
    OperationState,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
)
from stateback.providers.reference.store import ReferenceStore
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import (
    load_attempts,
    load_audits,
    make_submit,
)
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_lost_execute_response_verify_store_reaches_succeeded(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    store: ReferenceStore,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    assert executed.operation.state is OperationState.UNKNOWN
    assert store.get_by_resource_id("res-1") is not None
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED
    attempts = load_attempts(uow_factory, ids.operation_id)
    assert attempts[0].outcome is EffectOutcome.UNKNOWN
    assert attempts[0].state is AttemptState.COMPLETED
    assert recovered.verification_evidence is not None
    assert recovered.verification_evidence.outcome is EffectOutcome.APPLIED
    types = {event.event_type for event in load_audits(uow_factory, ids.operation_id)}
    assert AuditEventType.EXECUTION_EVIDENCE_RECORDED in types
    assert adapter._execute_scripts == [ReferenceExecuteScript.NOT_APPLIED_REJECTED]
