"""Provider capability boundary. Importing this package MUST NOT open sockets."""

from __future__ import annotations

from stateback.providers.exceptions import (
    DuplicateEffectRegistrationError,
    ProviderBoundaryError,
    UnsupportedEffectError,
)
from stateback.providers.normalize import evidence_for_unclassified_exception
from stateback.providers.protocol import ProviderAdapter
from stateback.providers.reference import (
    EFFECT_MUTATE_EVENTUAL,
    EFFECT_MUTATE_MITIGATING,
    EFFECT_MUTATE_NATURAL,
    EFFECT_MUTATE_NONE,
    EFFECT_MUTATE_PROVIDER_KEY,
    EFFECT_READ_RESOURCE,
    REFERENCE_DESCRIPTORS,
    REFERENCE_EFFECTS,
    REFERENCE_KEY_SEMANTICS,
    REFERENCE_PROVIDER,
    FixedClock,
    ReferenceAdapter,
    ReferenceCompensateScript,
    ReferenceExecuteScript,
    ReferenceStore,
    ReferenceVerifyScript,
)
from stateback.providers.registry import CapabilityRegistry
from stateback.providers.retry import (
    parse_replay_window_seconds,
    replay_window_has_elapsed,
)

__all__ = [
    "EFFECT_MUTATE_EVENTUAL",
    "EFFECT_MUTATE_MITIGATING",
    "EFFECT_MUTATE_NATURAL",
    "EFFECT_MUTATE_NONE",
    "EFFECT_MUTATE_PROVIDER_KEY",
    "EFFECT_READ_RESOURCE",
    "REFERENCE_DESCRIPTORS",
    "REFERENCE_EFFECTS",
    "REFERENCE_KEY_SEMANTICS",
    "REFERENCE_PROVIDER",
    "CapabilityRegistry",
    "DuplicateEffectRegistrationError",
    "FixedClock",
    "ProviderAdapter",
    "ProviderBoundaryError",
    "ReferenceAdapter",
    "ReferenceCompensateScript",
    "ReferenceExecuteScript",
    "ReferenceStore",
    "ReferenceVerifyScript",
    "UnsupportedEffectError",
    "evidence_for_unclassified_exception",
    "parse_replay_window_seconds",
    "replay_window_has_elapsed",
]
