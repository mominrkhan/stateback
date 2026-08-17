from __future__ import annotations

import pytest

from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_recovery_does_not_put_secret_material_in_reason_codes(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    codes = [recovered.reason_code]
    if recovered.decision is not None:
        codes.append(recovered.decision.reason_code)
    if recovered.transition is not None:
        codes.append(recovered.transition.reason_code)
    for code in codes:
        lowered = code.lower()
        assert "bearer " not in lowered
        assert "-----begin " not in lowered
