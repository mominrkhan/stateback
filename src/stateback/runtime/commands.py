"""Runtime command dataclasses. Callers inject every ID and timestamp source."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import JsonValue
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.runtime.ids import ExecuteIds, RecoverIds, SubmitIds

PHASE5_ENVIRONMENT = "phase5"


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitCommand:
    effect: EffectRef
    arguments: JsonValue
    requester: PrincipalRef
    metadata: tuple[tuple[str, str], ...]
    ids: SubmitIds
    correlation_id: str | None
    deployment_environment: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: ExecuteIds
    actor: PrincipalRef | None
    correlation_id: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoverCommand:
    operation_id: OpaqueId
    expected_version: int
    ids: RecoverIds
    actor: PrincipalRef | None
    correlation_id: str | None
