"""Persist a VerificationResult in its own unit of work. Does not apply a transition."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.enums import ErrorKind
from stateback.domain.verification import VerificationResult
from stateback.persistence.exceptions import PersistenceError
from stateback.persistence.uow import unit_of_work


def persist_verification_result(
    uow_factory: sessionmaker[Session],
    result: VerificationResult,
) -> None:
    with unit_of_work(uow_factory) as uow:
        loaded = uow.verifications.get(result.verification_id)
        if loaded is None:
            raise PersistenceError(
                "not_found",
                "verification request not found",
                error_kind=ErrorKind.PERSISTENCE,
            )
        _request, existing = loaded
        if existing is not None:
            if existing.outcome is result.outcome:
                return
            raise PersistenceError(
                "check_violation",
                "verification result already present",
                error_kind=ErrorKind.PERSISTENCE,
            )
        try:
            uow.verifications.complete(result)
        except PersistenceError as exc:
            if exc.reason_code != "check_violation":
                raise
            raced = uow.verifications.get(result.verification_id)
            if raced is None:
                raise
            _raced_request, present = raced
            if present is not None and present.outcome is result.outcome:
                return
            raise
