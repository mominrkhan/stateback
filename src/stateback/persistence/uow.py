from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from stateback.persistence.repositories import (
    ApprovalRepository,
    AttemptRepository,
    AuditRepository,
    CompensationAttemptRepository,
    CompensationRepository,
    OperationRepository,
    OutboxRepository,
    PolicyDecisionRepository,
    ReconciliationRepository,
    VerificationRepository,
    _reraise_db,
)


class UnitOfWork:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.operations = OperationRepository(session)
        self.attempts = AttemptRepository(session)
        self.policy_decisions = PolicyDecisionRepository(session)
        self.approvals = ApprovalRepository(session)
        self.verifications = VerificationRepository(session)
        self.compensations = CompensationRepository(session)
        self.compensation_attempts = CompensationAttemptRepository(session)
        self.audit_events = AuditRepository(session)
        self.outbox_events = OutboxRepository(session)
        self.reconciliation_decisions = ReconciliationRepository(session)

    def commit(self) -> None:
        try:
            self.session.commit()
        except (IntegrityError, DBAPIError) as exc:
            self.session.rollback()
            _reraise_db(exc)

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()


@contextmanager
def unit_of_work(factory: sessionmaker[Session]) -> Iterator[UnitOfWork]:
    session = factory()
    uow = UnitOfWork(session)
    try:
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
