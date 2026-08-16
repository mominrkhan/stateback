"""Reconciliation input/decision — `contracts/VERIFICATION_CONTRACT.md` §6–7."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import ReconciliationAction
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyObligations
from stateback.domain.verification import VerificationResult
from stateback.domain.wire import (
    parse_enum,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_DECISION_FIELDS = frozenset({"action", "reason_code"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationInput:
    operation: Operation
    attempts: tuple[ExecutionAttempt, ...]
    verification_result: VerificationResult
    provider_descriptor: EffectDescriptor
    policy_obligations: PolicyObligations

    def to_wire(self) -> dict[str, object]:
        return {
            "operation": self.operation.to_wire(),
            "attempts": [item.to_wire() for item in self.attempts],
            "verification_result": self.verification_result.to_wire(),
            "provider_descriptor": self.provider_descriptor.to_wire(),
            "policy_obligations": self.policy_obligations.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> ReconciliationInput:
        data = require_mapping(raw, type_name="ReconciliationInput")
        reject_unknown_keys(
            data,
            frozenset(
                {
                    "operation",
                    "attempts",
                    "verification_result",
                    "provider_descriptor",
                    "policy_obligations",
                }
            ),
            type_name="ReconciliationInput",
        )
        attempts_raw = require_key(data, "attempts", type_name="ReconciliationInput")
        if not isinstance(attempts_raw, list):
            raise ContractValidationError(
                "invalid_type",
                "ReconciliationInput.attempts must be an array",
            )
        return cls(
            operation=Operation.from_wire(
                require_key(data, "operation", type_name="ReconciliationInput")
            ),
            attempts=tuple(ExecutionAttempt.from_wire(item) for item in attempts_raw),
            verification_result=VerificationResult.from_wire(
                require_key(
                    data, "verification_result", type_name="ReconciliationInput"
                )
            ),
            provider_descriptor=EffectDescriptor.from_wire(
                require_key(
                    data, "provider_descriptor", type_name="ReconciliationInput"
                )
            ),
            policy_obligations=PolicyObligations.from_wire(
                require_key(data, "policy_obligations", type_name="ReconciliationInput")
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationDecision:
    action: ReconciliationAction
    reason_code: str

    def to_wire(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_wire(cls, raw: object) -> ReconciliationDecision:
        data = require_mapping(raw, type_name="ReconciliationDecision")
        reject_unknown_keys(data, _DECISION_FIELDS, type_name="ReconciliationDecision")
        return cls(
            action=parse_enum(
                ReconciliationAction,
                require_key(data, "action", type_name="ReconciliationDecision"),
                field="ReconciliationDecision.action",
            ),
            reason_code=parse_str(
                require_key(data, "reason_code", type_name="ReconciliationDecision"),
                field="ReconciliationDecision.reason_code",
            ),
        )
