"""Policy engine protocol. Evaluate only; no I/O."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stateback.policy.evaluation import PolicyEvaluation
from stateback.policy.inputs import PolicyInputs


@runtime_checkable
class PolicyEngine(Protocol):
    def evaluate(self, inputs: PolicyInputs) -> PolicyEvaluation: ...
