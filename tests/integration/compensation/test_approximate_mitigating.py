from __future__ import annotations

import pytest

from stateback.compensation.service import CompensationService
from stateback.domain.enums import CompensationKind, CompensationState, OperationState
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_MITIGATING,
    EFFECT_MUTATE_NATURAL,
)
from stateback.providers.reference.store import ReferenceStore
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import make_execute, make_start
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_approximate_success_exposes_approximate_kind(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_NATURAL), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.compensation is not None
    assert started.compensation.kind is CompensationKind.APPROXIMATE

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.kind is CompensationKind.APPROXIMATE
    assert executed.compensation.state is CompensationState.SUCCEEDED


def test_mitigating_success_exposes_mitigating_kind(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_MITIGATING), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation
    assert op.state is OperationState.SUCCEEDED

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    assert started.compensation is not None
    assert started.compensation.kind is CompensationKind.MITIGATING

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED
    assert executed.compensation is not None
    assert executed.compensation.kind is CompensationKind.MITIGATING


def test_reference_store_row_not_deleted(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(
        make_submit(seq, effect=EFFECT_MUTATE_MITIGATING), execute_ids(seq)
    )
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None
    compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )

    row = store.get_by_resource_id("res-1")
    assert row is not None
    assert row.mitigated is True
    assert row.applied is True
