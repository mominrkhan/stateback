from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import OperationState, PolicyVerdict
from stateback.policy import PolicyEvaluation, ScriptedPolicyEngine
from stateback.policy.evaluation import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
)
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.scripts import ReferenceExecuteScript
from stateback.providers.reference.store import ReferenceStore
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.service import RecoveryService
from tests.integration.recovery.conftest import make_recovery
from tests.integration.recovery.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit, rebuild_runtime
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_execution_require_verification_completes_via_recovery(
    uow_factory: sessionmaker[Session],
    registry: CapabilityRegistry,
    adapter: ReferenceAdapter,
    clock: FixedClock,
    store: ReferenceStore,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, require_verification=True
    )
    engine = ScriptedPolicyEngine()
    engine.enqueue(
        PolicyEvaluation(
            verdict=PolicyVerdict.ALLOW,
            reason_codes=("require_verify",),
            explanation=None,
            obligations=obligations,
            policy_revision=PHASE5_POLICY_REVISION,
        )
    )
    runtime = rebuild_runtime(uow_factory, registry, clock, policy_engine=engine)
    recovery = RecoveryService(
        session_factory=uow_factory,
        registry=registry,
        clock=clock,
    )
    ids = submit_ids(seq)
    executed = runtime.run(make_submit(seq, ids=ids), execute_ids(seq))
    assert executed.operation is not None
    assert executed.operation.state is OperationState.VERIFYING
    adapter.enqueue_execute(ReferenceExecuteScript.NOT_APPLIED_REJECTED)
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.SUCCEEDED
    assert len(store.all_resources()) == 1
    assert adapter._execute_scripts == [ReferenceExecuteScript.NOT_APPLIED_REJECTED]
