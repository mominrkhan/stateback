"""Policy evaluation inputs. No intent arguments or credentials."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import (
    CompensationKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.refs import EffectRef, PrincipalRef


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyInputs:
    operation_id: OpaqueId
    operation_version: int
    intent_digest: str
    requester: PrincipalRef
    effect: EffectRef
    risk_level: RiskLevel
    mutability: Mutability
    idempotency_mode: IdempotencyMode
    verification_mode: VerificationMode
    compensation_kind: CompensationKind
    metadata: tuple[tuple[str, str], ...]
    deployment_environment: str
