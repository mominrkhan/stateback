from __future__ import annotations

import pytest

from stateback.domain.enums import OperationState, PrincipalType
from stateback.domain.refs import PrincipalRef
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.effects import EFFECT_MUTATE_NONE
from stateback.providers.reference.scripts import (
    ReferenceExecuteScript,
    ReferenceVerifyScript,
)
from stateback.recovery.commands import OperatorVerificationCommand
from stateback.recovery.results import RecoveryDisposition
from stateback.recovery.service import RecoveryService
from stateback.runtime import SynchronousRuntime
from tests.integration.recovery.conftest import make_recovery, run_unknown_timeout
from tests.integration.recovery.idseq import IdSeq, recovery_ids
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids, submit_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

OPERATOR = PrincipalRef(type=PrincipalType.OPERATOR, id="op-1", display_name="Operator")


def test_manual_start_verification_from_manual_intervention(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_execute(ReferenceExecuteScript.UNKNOWN_TIMEOUT_AFTER_SEND)
    ids = submit_ids(seq)
    executed = runtime.run(
        make_submit(seq, ids=ids, effect=EFFECT_MUTATE_NONE),
        execute_ids(seq),
    )
    assert executed.operation is not None
    recovered = recovery.recover(
        make_recovery(seq, ids.operation_id, executed.operation.version)
    )
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.MANUAL_INTERVENTION
    started = recovery.start_operator_verification(
        OperatorVerificationCommand(
            operation_id=ids.operation_id,
            expected_version=recovered.operation.version,
            ids=recovery_ids(seq),
            actor=OPERATOR,
            correlation_id=None,
        )
    )
    assert started.disposition is RecoveryDisposition.REJECTED
    assert started.reason_code == "verification_unsupported"


def test_manual_start_from_unknown_rejected(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    seq: IdSeq,
) -> None:
    op = run_unknown_timeout(runtime, seq)
    started = recovery.start_operator_verification(
        OperatorVerificationCommand(
            operation_id=op.operation_id,
            expected_version=op.version,
            ids=recovery_ids(seq),
            actor=OPERATOR,
            correlation_id=None,
        )
    )
    assert started.disposition is RecoveryDisposition.REJECTED
    assert started.reason_code == "source_state_mismatch"


def test_operator_start_after_inconsistent_then_forced_applied(
    runtime: SynchronousRuntime,
    recovery: RecoveryService,
    adapter: ReferenceAdapter,
    seq: IdSeq,
) -> None:
    adapter.enqueue_verify(ReferenceVerifyScript.UNKNOWN_INCONSISTENT)
    op = run_unknown_timeout(runtime, seq)
    recovered = recovery.recover(make_recovery(seq, op.operation_id, op.version))
    assert recovered.operation is not None
    assert recovered.operation.state is OperationState.MANUAL_INTERVENTION
    adapter.enqueue_verify(ReferenceVerifyScript.APPLIED)
    started = recovery.start_operator_verification(
        OperatorVerificationCommand(
            operation_id=op.operation_id,
            expected_version=recovered.operation.version,
            ids=recovery_ids(seq),
            actor=OPERATOR,
            correlation_id=None,
        )
    )
    assert started.operation is not None
    assert started.operation.state is OperationState.SUCCEEDED
    assert started.transition is not None
