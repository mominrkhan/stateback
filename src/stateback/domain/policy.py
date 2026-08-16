"""PolicyDecision, obligations, and Approval — `contracts/POLICY_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CONTRACT_VERSION,
    ApprovalState,
    PolicyVerdict,
)
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import PrincipalRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_bool,
    parse_contract_version,
    parse_enum,
    parse_int,
    parse_optional_int,
    parse_optional_str,
    parse_str,
    parse_str_list,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_OBLIGATION_FIELDS = frozenset(
    {
        "require_verification",
        "max_automatic_execution_attempts",
        "max_automatic_recovery_attempts",
        "automatic_compensation_allowed",
        "operator_reason_required",
        "approval_expires_at",
    }
)
_DECISION_FIELDS = frozenset(
    {
        "contract_version",
        "policy_decision_id",
        "operation_id",
        "operation_version",
        "intent_digest",
        "verdict",
        "reason_codes",
        "explanation",
        "obligations",
        "policy_revision",
        "evaluated_at",
    }
)
_APPROVAL_FIELDS = frozenset(
    {
        "contract_version",
        "approval_id",
        "operation_id",
        "operation_version",
        "intent_digest",
        "policy_decision_id",
        "state",
        "requested_at",
        "expires_at",
        "decided_at",
        "decided_by",
        "reason",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyObligations:
    require_verification: bool
    max_automatic_execution_attempts: int | None
    max_automatic_recovery_attempts: int | None
    automatic_compensation_allowed: bool
    operator_reason_required: bool
    approval_expires_at: UtcTimestamp | None

    def to_wire(self) -> dict[str, object]:
        return {
            "require_verification": self.require_verification,
            "max_automatic_execution_attempts": self.max_automatic_execution_attempts,
            "max_automatic_recovery_attempts": self.max_automatic_recovery_attempts,
            "automatic_compensation_allowed": self.automatic_compensation_allowed,
            "operator_reason_required": self.operator_reason_required,
            "approval_expires_at": (
                None
                if self.approval_expires_at is None
                else self.approval_expires_at.to_wire()
            ),
        }

    @classmethod
    def from_wire(cls, raw: object) -> PolicyObligations:
        data = require_mapping(raw, type_name="PolicyObligations")
        reject_unknown_keys(data, _OBLIGATION_FIELDS, type_name="PolicyObligations")
        expires_raw = optional_key(data, "approval_expires_at")
        return cls(
            require_verification=parse_bool(
                require_key(
                    data, "require_verification", type_name="PolicyObligations"
                ),
                field="PolicyObligations.require_verification",
            ),
            max_automatic_execution_attempts=parse_optional_int(
                optional_key(data, "max_automatic_execution_attempts"),
                field="PolicyObligations.max_automatic_execution_attempts",
                minimum=0,
            ),
            max_automatic_recovery_attempts=parse_optional_int(
                optional_key(data, "max_automatic_recovery_attempts"),
                field="PolicyObligations.max_automatic_recovery_attempts",
                minimum=0,
            ),
            automatic_compensation_allowed=parse_bool(
                require_key(
                    data,
                    "automatic_compensation_allowed",
                    type_name="PolicyObligations",
                ),
                field="PolicyObligations.automatic_compensation_allowed",
            ),
            operator_reason_required=parse_bool(
                require_key(
                    data, "operator_reason_required", type_name="PolicyObligations"
                ),
                field="PolicyObligations.operator_reason_required",
            ),
            approval_expires_at=(
                None
                if expires_raw is None
                else UtcTimestamp.from_wire(
                    expires_raw, field="PolicyObligations.approval_expires_at"
                )
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyDecision:
    contract_version: str
    policy_decision_id: OpaqueId
    operation_id: OpaqueId
    operation_version: int
    intent_digest: str
    verdict: PolicyVerdict
    reason_codes: tuple[str, ...]
    explanation: str | None
    obligations: PolicyObligations
    policy_revision: str
    evaluated_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "PolicyDecision.contract_version must be v1",
            )
        if self.operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "operation_version must be >= 1",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "policy_decision_id": self.policy_decision_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "operation_version": self.operation_version,
            "intent_digest": self.intent_digest,
            "verdict": self.verdict.value,
            "reason_codes": list(self.reason_codes),
            "explanation": self.explanation,
            "obligations": self.obligations.to_wire(),
            "policy_revision": self.policy_revision,
            "evaluated_at": self.evaluated_at.to_wire(),
        }

    @classmethod
    def from_wire(cls, raw: object) -> PolicyDecision:
        data = require_mapping(raw, type_name="PolicyDecision")
        reject_unknown_keys(data, _DECISION_FIELDS, type_name="PolicyDecision")
        parse_contract_version(
            require_key(data, "contract_version", type_name="PolicyDecision"),
            type_name="PolicyDecision",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            policy_decision_id=OpaqueId.from_wire(
                require_key(data, "policy_decision_id", type_name="PolicyDecision"),
                field="PolicyDecision.policy_decision_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="PolicyDecision"),
                field="PolicyDecision.operation_id",
            ),
            operation_version=parse_int(
                require_key(data, "operation_version", type_name="PolicyDecision"),
                field="PolicyDecision.operation_version",
                minimum=1,
            ),
            intent_digest=parse_str(
                require_key(data, "intent_digest", type_name="PolicyDecision"),
                field="PolicyDecision.intent_digest",
            ),
            verdict=parse_enum(
                PolicyVerdict,
                require_key(data, "verdict", type_name="PolicyDecision"),
                field="PolicyDecision.verdict",
            ),
            reason_codes=parse_str_list(
                require_key(data, "reason_codes", type_name="PolicyDecision"),
                field="PolicyDecision.reason_codes",
            ),
            explanation=parse_optional_str(
                optional_key(data, "explanation"),
                field="PolicyDecision.explanation",
            ),
            obligations=PolicyObligations.from_wire(
                require_key(data, "obligations", type_name="PolicyDecision")
            ),
            policy_revision=parse_str(
                require_key(data, "policy_revision", type_name="PolicyDecision"),
                field="PolicyDecision.policy_revision",
            ),
            evaluated_at=UtcTimestamp.from_wire(
                require_key(data, "evaluated_at", type_name="PolicyDecision"),
                field="PolicyDecision.evaluated_at",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Approval:
    contract_version: str
    approval_id: OpaqueId
    operation_id: OpaqueId
    operation_version: int
    intent_digest: str
    policy_decision_id: OpaqueId
    state: ApprovalState
    requested_at: UtcTimestamp
    expires_at: UtcTimestamp | None
    decided_at: UtcTimestamp | None
    decided_by: PrincipalRef | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "Approval.contract_version must be v1",
            )
        if self.operation_version < 1:
            raise ContractValidationError(
                "invalid_range",
                "operation_version must be >= 1",
            )
        if self.state is ApprovalState.PENDING:
            if self.decided_at is not None or self.decided_by is not None:
                raise ContractValidationError(
                    "illegal_combination",
                    "PENDING approval must not have a decision",
                )
        else:
            if self.decided_at is None:
                raise ContractValidationError(
                    "illegal_combination",
                    "terminal approval requires decided_at",
                )

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "approval_id": self.approval_id.to_wire(),
            "operation_id": self.operation_id.to_wire(),
            "operation_version": self.operation_version,
            "intent_digest": self.intent_digest,
            "policy_decision_id": self.policy_decision_id.to_wire(),
            "state": self.state.value,
            "requested_at": self.requested_at.to_wire(),
            "expires_at": None
            if self.expires_at is None
            else self.expires_at.to_wire(),
            "decided_at": None
            if self.decided_at is None
            else self.decided_at.to_wire(),
            "decided_by": None
            if self.decided_by is None
            else self.decided_by.to_wire(),
            "reason": self.reason,
        }

    @classmethod
    def from_wire(cls, raw: object) -> Approval:
        data = require_mapping(raw, type_name="Approval")
        reject_unknown_keys(data, _APPROVAL_FIELDS, type_name="Approval")
        parse_contract_version(
            require_key(data, "contract_version", type_name="Approval"),
            type_name="Approval",
        )
        expires_raw = optional_key(data, "expires_at")
        decided_raw = optional_key(data, "decided_at")
        decided_by_raw = optional_key(data, "decided_by")
        return cls(
            contract_version=CONTRACT_VERSION,
            approval_id=OpaqueId.from_wire(
                require_key(data, "approval_id", type_name="Approval"),
                field="Approval.approval_id",
            ),
            operation_id=OpaqueId.from_wire(
                require_key(data, "operation_id", type_name="Approval"),
                field="Approval.operation_id",
            ),
            operation_version=parse_int(
                require_key(data, "operation_version", type_name="Approval"),
                field="Approval.operation_version",
                minimum=1,
            ),
            intent_digest=parse_str(
                require_key(data, "intent_digest", type_name="Approval"),
                field="Approval.intent_digest",
            ),
            policy_decision_id=OpaqueId.from_wire(
                require_key(data, "policy_decision_id", type_name="Approval"),
                field="Approval.policy_decision_id",
            ),
            state=parse_enum(
                ApprovalState,
                require_key(data, "state", type_name="Approval"),
                field="Approval.state",
            ),
            requested_at=UtcTimestamp.from_wire(
                require_key(data, "requested_at", type_name="Approval"),
                field="Approval.requested_at",
            ),
            expires_at=(
                None
                if expires_raw is None
                else UtcTimestamp.from_wire(expires_raw, field="Approval.expires_at")
            ),
            decided_at=(
                None
                if decided_raw is None
                else UtcTimestamp.from_wire(decided_raw, field="Approval.decided_at")
            ),
            decided_by=(
                None
                if decided_by_raw is None
                else PrincipalRef.from_wire(decided_by_raw)
            ),
            reason=parse_optional_str(
                optional_key(data, "reason"),
                field="Approval.reason",
            ),
        )
