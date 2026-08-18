"""Model-completion boundary for optional semantic assistance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SemanticModelUnavailable(Exception):
    """The optional model could not produce a response."""


class SemanticModelInvalidResponse(Exception):
    """The optional model service returned an invalid envelope."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelCompletion:
    content: str
    provider: str
    model: str


class SemanticModel(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete(
        self, *, prompt: str, output_schema: dict[str, object]
    ) -> ModelCompletion: ...
