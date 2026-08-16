from __future__ import annotations

import pytest

from stateback.domain.crash import interpret_execution_crash
from stateback.domain.enums import AttemptState, CrashInterpretation, OperationState

pytestmark = pytest.mark.unit


def test_ready_crash_is_no_provider_attempt() -> None:
    decision = interpret_execution_crash(
        operation_state=OperationState.READY,
        attempt_state=None,
    )
    assert decision.interpretation is CrashInterpretation.NO_PROVIDER_ATTEMPT


def test_executing_started_is_potentially_unknown() -> None:
    decision = interpret_execution_crash(
        operation_state=OperationState.EXECUTING,
        attempt_state=AttemptState.STARTED,
    )
    assert decision.interpretation is CrashInterpretation.POTENTIALLY_UNKNOWN


def test_completed_attempt_uses_durable_evidence() -> None:
    decision = interpret_execution_crash(
        operation_state=OperationState.EXECUTING,
        attempt_state=AttemptState.COMPLETED,
    )
    assert decision.interpretation is CrashInterpretation.USE_DURABLE_EVIDENCE
