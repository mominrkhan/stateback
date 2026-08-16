"""FIFO scripted policy engine for tests."""

from __future__ import annotations

from stateback.policy.allow_all import AllowAllPolicyEngine
from stateback.policy.evaluation import PolicyEvaluation
from stateback.policy.inputs import PolicyInputs
from stateback.policy.protocol import PolicyEngine


class ScriptedPolicyEngine:
    def __init__(self, default: PolicyEngine | None = None) -> None:
        self._default: PolicyEngine = (
            default if default is not None else AllowAllPolicyEngine()
        )
        self._queue: list[PolicyEvaluation] = []

    def enqueue(self, evaluation: PolicyEvaluation) -> None:
        self._queue.append(evaluation)

    def evaluate(self, inputs: PolicyInputs) -> PolicyEvaluation:
        if self._queue:
            return self._queue.pop(0)
        return self._default.evaluate(inputs)
