from __future__ import annotations

from stateback.domain.enums import ErrorKind


class PersistenceError(Exception):
    def __init__(
        self, reason_code: str, message: str, *, error_kind: ErrorKind
    ) -> None:
        if not reason_code:
            raise ValueError("reason_code must be non-empty")
        if not message:
            raise ValueError("message must be non-empty")
        self.reason_code = reason_code
        self.error_kind = error_kind
        super().__init__(message)


class DuplicateKeyError(PersistenceError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(reason_code, message, error_kind=ErrorKind.PERSISTENCE)


class ConcurrencyConflictError(PersistenceError):
    def __init__(self, message: str) -> None:
        super().__init__(
            "concurrency_conflict",
            message,
            error_kind=ErrorKind.CONCURRENCY_CONFLICT,
        )


class NotFoundError(PersistenceError):
    def __init__(self, message: str) -> None:
        super().__init__("not_found", message, error_kind=ErrorKind.PERSISTENCE)


class AppendOnlyViolationError(PersistenceError):
    def __init__(self, message: str) -> None:
        super().__init__(
            "append_only_violation",
            message,
            error_kind=ErrorKind.PERSISTENCE,
        )


class MalformedRowError(PersistenceError):
    def __init__(self, message: str) -> None:
        super().__init__("malformed_row", message, error_kind=ErrorKind.PERSISTENCE)
