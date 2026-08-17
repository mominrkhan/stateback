from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import EffectOutcome, OperationState
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
from tests.integration.runtime.conftest import load_attempts

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_verify_malformed_stays_unknown(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_MALFORMED)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.UNKNOWN
    assert recovered.verification_evidence is not None
    assert recovered.verification_evidence.outcome is EffectOutcome.UNKNOWN


def test_verify_inconsistent_goes_manual_intervention(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    uow_factory: sessionmaker[Session],
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.MANUAL_INTERVENTION
    attempts = load_attempts(uow_factory, op.operation_id)
    assert len(attempts) == 1
    rows = load_verifications(uow_factory, op.operation_id)
    assert len(rows) == 1
    _request, result = rows[0]
    assert result is not None
    assert result.outcome is EffectOutcome.UNKNOWN
