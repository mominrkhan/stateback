from __future__ import annotations

import pytest

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState
from stateback.providers.reference.effects import EFFECT_MUTATE_NONE
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import make_start
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_mutate_none_start_is_not_eligible(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_NONE), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.disposition is CompensationDisposition.NOT_ELIGIBLE
    assert started.reason_code == "compensation_kind_none"


def test_compensate_unsupported_not_called_when_none_kind(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_NONE), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.disposition is CompensationDisposition.NOT_ELIGIBLE
    assert op.compensation_id is None
