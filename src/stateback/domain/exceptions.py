"""Domain contract-validation errors.

These are construction/parse failures, not provider EffectOutcome.
"""

from __future__ import annotations


class ContractValidationError(ValueError):
    """Raised when a value violates a v1 canonical contract.

    `reason_code` is a stable programmatic token. `message` is safe to log.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        if not reason_code:
            msg = "reason_code must be non-empty"
            raise ValueError(msg)
        if not message:
            msg = "message must be non-empty"
            raise ValueError(msg)
        self.reason_code = reason_code
        super().__init__(message)
