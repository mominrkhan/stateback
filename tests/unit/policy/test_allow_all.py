from __future__ import annotations

import pytest

from stateback.domain.enums import Mutability, PolicyVerdict
from stateback.policy import (
    PHASE5_DEFAULT_OBLIGATIONS,
    PHASE5_POLICY_REVISION,
    AllowAllPolicyEngine,
)
from tests.unit.runtime.fixtures import make_policy_inputs

pytestmark = pytest.mark.unit


def test_allow_all_returns_allow_and_phase5_revision() -> None:
    engine = AllowAllPolicyEngine()
    evaluation = engine.evaluate(make_policy_inputs())
    assert evaluation.verdict is PolicyVerdict.ALLOW
    assert evaluation.reason_codes == ("phase5.allow_all",)
    assert evaluation.policy_revision == PHASE5_POLICY_REVISION
    assert evaluation.obligations == PHASE5_DEFAULT_OBLIGATIONS


def test_allow_all_does_not_call_provider() -> None:
    engine = AllowAllPolicyEngine()
    evaluation = engine.evaluate(make_policy_inputs(mutability=Mutability.READ_ONLY))
    assert evaluation.verdict is PolicyVerdict.ALLOW
    assert "execute" not in type(engine).__dict__
