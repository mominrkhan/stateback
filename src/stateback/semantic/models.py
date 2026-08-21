"""Typed advisory audit-summary models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stateback.domain.audit import AuditEvent
from stateback.domain.operation import Operation
from stateback.domain.secrets import key_is_forbidden, value_is_forbidden

CONTRACT_VERSION = "v1"
PROMPT_VERSION = "audit-summary-v1"
MAX_AUDIT_EVENTS = 200
MAX_MODEL_OUTPUT_BYTES = 64 * 1024
MIN_CONFIDENCE = 0.5


class SemanticStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ABSTAINED = "ABSTAINED"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelKeyEvent(StrictModel):
    sequence: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=500)


class ModelSummaryOutput(StrictModel):
    status: Literal["AVAILABLE", "ABSTAINED"]
    summary: str | None = Field(default=None, max_length=2000)
    key_events: list[ModelKeyEvent] = Field(default_factory=list, max_length=20)
    unresolved_uncertainties: list[str] = Field(default_factory=list, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_status_shape(self) -> ModelSummaryOutput:
        if any(not item.description.strip() for item in self.key_events):
            raise ValueError("key-event descriptions must contain text")
        if any(
            not item.strip() or len(item) > 500
            for item in self.unresolved_uncertainties
        ):
            raise ValueError("uncertainties must contain 1-500 characters")
        if self.status == "AVAILABLE":
            if (
                self.summary is None
                or not self.summary.strip()
                or self.confidence is None
            ):
                raise ValueError("available output requires summary and confidence")
        elif (
            self.summary is not None
            or self.key_events
            or self.unresolved_uncertainties
            or self.confidence is not None
        ):
            raise ValueError("abstained output cannot contain advisory content")
        return self


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticKeyEvent:
    sequence: int
    description: str

    def to_wire(self) -> dict[str, object]:
        return {"sequence": self.sequence, "description": self.description}


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticProvenance:
    provider: str | None
    model: str | None
    prompt_version: str = PROMPT_VERSION
    output_schema_version: str = CONTRACT_VERSION

    def to_wire(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "output_schema_version": self.output_schema_version,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticSummary:
    status: SemanticStatus
    summary: str | None
    key_events: tuple[SemanticKeyEvent, ...]
    unresolved_uncertainties: tuple[str, ...]
    confidence: float | None
    summarized_operation_version: int
    summarized_through_sequence: int
    provenance: SemanticProvenance
    reason_code: str

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": CONTRACT_VERSION,
            "advisory": True,
            "status": self.status.value,
            "summary": self.summary,
            "key_events": [item.to_wire() for item in self.key_events],
            "unresolved_uncertainties": list(self.unresolved_uncertainties),
            "confidence": self.confidence,
            "summarized_operation_version": self.summarized_operation_version,
            "summarized_through_sequence": self.summarized_through_sequence,
            "provenance": self.provenance.to_wire(),
            "reason_code": self.reason_code,
        }


def safe_text(value: str) -> str:
    if key_is_forbidden(value) or value_is_forbidden(value):
        return "[REDACTED]"
    return value[:500]


def model_input(
    operation: Operation, audit: tuple[AuditEvent, ...]
) -> dict[str, object]:
    return {
        "effect": {
            "provider": safe_text(operation.intent.effect.provider),
            "action": safe_text(operation.intent.effect.action),
            "version": safe_text(operation.intent.effect.version),
        },
        "operation_state": operation.state.value,
        "operation_version": operation.version,
        "audit": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type.value,
                "reason_code": safe_text(event.reason_code),
                "from_state": (
                    None if event.from_state is None else event.from_state.value
                ),
                "to_state": None if event.to_state is None else event.to_state.value,
                "created_at": event.created_at.to_wire(),
            }
            for event in audit
        ],
    }


def empty_summary(
    *,
    status: SemanticStatus,
    reason_code: str,
    operation: Operation,
    audit: tuple[AuditEvent, ...],
    provider: str | None,
    model: str | None,
) -> SemanticSummary:
    return SemanticSummary(
        status=status,
        summary=None,
        key_events=(),
        unresolved_uncertainties=(),
        confidence=None,
        summarized_operation_version=operation.version,
        summarized_through_sequence=audit[-1].sequence if audit else 0,
        provenance=SemanticProvenance(provider=provider, model=model),
        reason_code=reason_code,
    )
