"""Programming and registry errors at the provider boundary.

These are not `NormalizedError` and MUST NOT substitute for
`EffectOutcome.UNKNOWN`.
"""

from __future__ import annotations

from stateback.domain.refs import EffectRef


class ProviderBoundaryError(Exception):
    """Base class for adapter/registry programming errors."""


class UnsupportedEffectError(ProviderBoundaryError):
    def __init__(self, effect: EffectRef) -> None:
        self.effect = effect
        super().__init__(
            f"effect {effect.provider}/{effect.action}/{effect.version} "
            "is not supported by this adapter"
        )


class DuplicateEffectRegistrationError(ProviderBoundaryError):
    def __init__(self, effect: EffectRef) -> None:
        self.effect = effect
        super().__init__(
            f"effect {effect.provider}/{effect.action}/{effect.version} "
            "is already registered"
        )
