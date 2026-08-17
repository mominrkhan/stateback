"""Forward-safe SDK views over public v1 payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from stateback.domain.enums import FORWARD_TERMINAL_STATES, OperationState


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationStatus:
    operation_id: str
    state: str
    version: int
    raw: Mapping[str, object]

    @classmethod
    def from_wire(cls, payload: object) -> OperationStatus:
        if not isinstance(payload, dict):
            raise ValueError("operation payload must be an object")
        if payload.get("contract_version") != "v1":
            raise ValueError("unsupported contract version")
        operation_id = payload.get("operation_id")
        state = payload.get("state")
        version = payload.get("version")
        if (
            not isinstance(operation_id, str)
            or not isinstance(state, str)
            or isinstance(version, bool)
            or not isinstance(version, int)
        ):
            raise ValueError("malformed operation payload")
        return cls(
            operation_id=operation_id,
            state=state,
            version=version,
            raw=MappingProxyType(dict(payload)),
        )

    @property
    def known_state(self) -> OperationState | None:
        try:
            return OperationState(self.state)
        except ValueError:
            return None

    @property
    def is_forward_terminal(self) -> bool:
        state = self.known_state
        return state is not None and state in FORWARD_TERMINAL_STATES


class WaitOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True, kw_only=True)
class WaitResult:
    outcome: WaitOutcome
    operation: OperationStatus
