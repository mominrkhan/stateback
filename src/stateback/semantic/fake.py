"""Deterministic semantic model used by correctness tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from stateback.semantic.protocol import ModelCompletion


@dataclass(slots=True, kw_only=True)
class DeterministicSemanticModel:
    content: str
    provider: str = "deterministic_fake"
    model: str = "audit-summary-fixture-v1"
    prompts: list[str] = field(default_factory=list)
    schemas: list[dict[str, object]] = field(default_factory=list)

    def complete(
        self, *, prompt: str, output_schema: dict[str, object]
    ) -> ModelCompletion:
        self.prompts.append(prompt)
        self.schemas.append(output_schema)
        return ModelCompletion(
            content=self.content,
            provider=self.provider,
            model=self.model,
        )
