from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import OperationState, PolicyVerdict
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import ReferenceVerifyScript
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    make_execute,
    make_recover,
    make_start,
    run_to_succeeded_via_recovery,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_recover_compensated_is_already_applied(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    recovered = compensation.recover(
        make_recover(seq, executed.operation.operation_id, executed.operation.version)
    )
    assert recovered.disposition is CompensationDisposition.ACCEPTED
    assert recovered.reason_code == "already_applied"


def test_recover_verifying_with_complete_result_does_not_verify_again(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("allow",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    compensation = CompensationService(
        session_factory=uow_factory, registry=registry, clock=clock
    )
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    op = run_to_succeeded_via_recovery(runtime, recovery, seq)

    started = compensation.start(make_start(seq, op.operation_id, op.version))
    assert started.operation is not None

    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    executed = compensation.execute(
        make_execute(seq, started.operation.operation_id, started.operation.version)
    )
    assert executed.operation is not None
    assert executed.operation.state is OperationState.COMPENSATED

    # Re-running recover when already compensated does not call verify again
    recovered = compensation.recover(
        make_recover(seq, executed.operation.operation_id, executed.operation.version)
    )
    assert recovered.disposition is CompensationDisposition.ACCEPTED
    assert not adapter._verify_scripts
