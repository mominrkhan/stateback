"""Policy evaluation result and Phase 5 default obligations."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import PolicyVerdict
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.policy import PolicyObligations
from stateback.domain.secrets import reject_secrets_in_str_map

PHASE5_POLICY_REVISION = "stateback.phase5.allow-all.v1"

PHASE5_DEFAULT_OBLIGATIONS = PolicyObligations(
    require_verification=False,
    max_automatic_execution_attempts=1,
    max_automatic_recovery_attempts=None,
    automatic_compensation_allowed=False,
    operator_reason_required=False,
    approval_expires_at=None,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyEvaluation:
    verdict: PolicyVerdict
    reason_codes: tuple[str, ...]
    explanation: str | None
    obligations: PolicyObligations
    policy_revision: str

    def __post_init__(self) -> None:
        if not self.reason_codes or any(code == "" for code in self.reason_codes):
            raise ContractValidationError(
                "empty_string",
                "PolicyEvaluation.reason_codes must be a non-empty tuple of "
                "non-empty strings",
            )
        if self.policy_revision == "":
            raise ContractValidationError(
                "empty_string",
                "PolicyEvaluation.policy_revision must be a non-empty string",
            )
        if self.explanation is not None:
            reject_secrets_in_str_map(
                (("explanation", self.explanation),),
                field="PolicyEvaluation",
            )
