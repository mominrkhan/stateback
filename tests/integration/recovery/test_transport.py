from __future__ import annotations

import pytest

from stateback.domain.enums import EffectOutcome, OperationState
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import ReferenceVerifyScript
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery, run_unknown_timeout
from tests.integration.recovery.idseq import IdSeq

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.benchmark_correctness,
]


def test_verify_timeout_stays_unknown_not_failed(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_TRANSPORT)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.UNKNOWN
    assert recovered.verification_evidence is not None
    assert recovered.verification_evidence.outcome is EffectOutcome.UNKNOWN
