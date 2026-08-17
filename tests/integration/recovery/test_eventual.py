from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState
from stateback.policy import AllowAllPolicyEngine
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import EFFECT_MUTATE_EVENTUAL
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _eventual_runtime(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    *,
    visibility_delay_seconds: int,
) -> tuple[SynchronousRuntime, RecoveryService, ReferenceAdapter, ReferenceStore]:
    store = ReferenceStore()
    adapter = ReferenceAdapter(
        store=store,
        clock=clock,
        visibility_delay_seconds=visibility_delay_seconds,
    )
    registry = CapabilityRegistry()
    registry.register(adapter)
    runtime = SynchronousRuntime(
        session_factory=uow_factory,
        registry=registry,
        policy_engine=AllowAllPolicyEngine(),
        clock=clock,
    )
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    return runtime, recovery, adapter, store


def test_eventual_not_found_inside_visibility_is_unknown(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    runtime, recovery, adapter, _store = _eventual_runtime(
        uow_factory, clock, visibility_delay_seconds=60
    )
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(
        make_submit(seq, ids=ids, effect=EFFECT_MUTATE_EVENTUAL),
        execute_ids(seq),
    )
    assert executed.operation is not None
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.UNKNOWN


def test_eventual_found_after_visibility_is_succeeded(
    uow_factory: sessionmaker[Session],
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    runtime, recovery, adapter, _store = _eventual_runtime(
        uow_factory, clock, visibility_delay_seconds=60
    )
    adapter.enqueue_execute(ReferenceExecuteScript.APPLIED_RESPONSE_LOST)
    ids = submit_ids(seq)
    executed = runtime.run(
        make_submit(seq, ids=ids, effect=EFFECT_MUTATE_EVENTUAL),
        execute_ids(seq),
    )
    assert executed.operation is not None
    first = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert first.operation is not None
    assert first.operation.state is OperationState.UNKNOWN
    clock.advance(60)
    second = recovery.recover(
        make_recovery(seq, ids.operation_id, first.operation.version)
    )
    assert second.operation is not None
    assert second.operation.state is OperationState.SUCCEEDED
