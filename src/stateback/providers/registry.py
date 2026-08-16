"""In-process capability registry keyed by EffectRef."""

from __future__ import annotations

from stateback.domain.capability import EffectDescriptor
from stateback.domain.enums import EffectOutcome, IdempotencyMode, RetrySafetyVerdict
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.refs import EffectRef
from stateback.domain.retry_safety import (
    RetrySafetyDecision,
    evaluate_effect_retry_safety,
)
from stateback.domain.time import UtcTimestamp
from stateback.providers.exceptions import (
    DuplicateEffectRegistrationError,
    UnsupportedEffectError,
)
from stateback.providers.protocol import ProviderAdapter
from stateback.providers.retry import replay_window_has_elapsed


class CapabilityRegistry:
    def __init__(self) -> None:
        self._order: list[EffectRef] = []
        self._adapters: dict[EffectRef, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        effects = adapter.supported_effects()
        if not effects:
            raise ContractValidationError(
                "empty_string",
                "adapter.supported_effects must be non-empty",
            )
        pending: list[tuple[EffectRef, ProviderAdapter]] = []
        for effect in effects:
            if effect in self._adapters:
                raise DuplicateEffectRegistrationError(effect)
            desc = adapter.descriptor(effect)
            if desc.effect != effect:
                raise ContractValidationError(
                    "illegal_combination",
                    "descriptor.effect must match supported effect",
                )
            pending.append((effect, adapter))
        for effect, registered in pending:
            self._adapters[effect] = registered
            self._order.append(effect)

    def listed_effects(self) -> tuple[EffectRef, ...]:
        return tuple(self._order)

    def descriptor(self, effect: EffectRef) -> EffectDescriptor:
        return self.adapter_for(effect).descriptor(effect)

    def adapter_for(self, effect: EffectRef) -> ProviderAdapter:
        adapter = self._adapters.get(effect)
        if adapter is None:
            raise UnsupportedEffectError(effect)
        return adapter

    def evaluate_retry_safety(
        self,
        *,
        effect: EffectRef,
        execution_outcome: EffectOutcome | None,
        verification_outcome: EffectOutcome | None,
        now: UtcTimestamp,
        first_attempt_at: UtcTimestamp | None = None,
        insufficient_signal: str | None = None,
    ) -> RetrySafetyDecision:
        desc = self.descriptor(effect)
        if insufficient_signal is not None:
            return evaluate_effect_retry_safety(
                execution_outcome=execution_outcome,
                verification_outcome=verification_outcome,
                idempotency_mode=desc.idempotency_mode,
                insufficient_signal=insufficient_signal,
            )
        if desc.idempotency_mode is IdempotencyMode.PROVIDER_KEY:
            if first_attempt_at is None:
                return RetrySafetyDecision(
                    verdict=RetrySafetyVerdict.UNSAFE,
                    basis=None,
                    reason_code="provider_key_replay_window_unknown_start",
                )
            semantics = desc.provider_key_semantics
            if semantics is None:
                return evaluate_effect_retry_safety(
                    execution_outcome=execution_outcome,
                    verification_outcome=verification_outcome,
                    idempotency_mode=IdempotencyMode.PROVIDER_KEY,
                )
            elapsed = replay_window_has_elapsed(
                semantics=semantics,
                started_at=first_attempt_at,
                now=now,
            )
            return evaluate_effect_retry_safety(
                execution_outcome=execution_outcome,
                verification_outcome=verification_outcome,
                idempotency_mode=IdempotencyMode.PROVIDER_KEY,
                provider_key_semantics=semantics,
                replay_window_elapsed=elapsed,
            )
        if desc.idempotency_mode is IdempotencyMode.NATURAL:
            return evaluate_effect_retry_safety(
                execution_outcome=execution_outcome,
                verification_outcome=verification_outcome,
                idempotency_mode=IdempotencyMode.NATURAL,
                natural_declaration_tested=True,
            )
        return evaluate_effect_retry_safety(
            execution_outcome=execution_outcome,
            verification_outcome=verification_outcome,
            idempotency_mode=IdempotencyMode.NONE,
        )
