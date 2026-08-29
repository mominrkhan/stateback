"""Transport-neutral application request and result models."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.jsonutil import JsonValue
from stateback.domain.refs import EffectRef


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmitOperationRequest:
    effect: EffectRef
    arguments: JsonValue
    metadata: tuple[tuple[str, str], ...]
    deployment_environment: str


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationSearch:
    state: str | None = None
    attention: bool = False
    provider: str | None = None
    created_from: str | None = None
    created_to: str | None = None
    cursor: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
