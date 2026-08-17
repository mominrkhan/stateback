"""Thin persistence wrappers shared by start/execute/recover."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyDecision
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.exceptions import NotFoundError
from stateback.persistence.uow import unit_of_work
from stateback.transitions.commands import TransitionCommand
from stateback.transitions.results import TransitionResult
from stateback.transitions.service import TransitionService


def apply_committed(
    factory: sessionmaker[Session],
    transitions: TransitionService,
    command: TransitionCommand,
) -> TransitionResult:
    with unit_of_work(factory) as uow:
        return transitions.apply(uow, command)


def load_operation(factory: sessionmaker[Session], operation_id: OpaqueId) -> Operation:
    with unit_of_work(factory) as uow:
        op = uow.operations.get(operation_id)
        if op is None:
            raise NotFoundError("operation not found")
        return op


def load_compensation(
    factory: sessionmaker[Session], compensation_id: OpaqueId
) -> Compensation | None:
    with unit_of_work(factory) as uow:
        return uow.compensations.get(compensation_id)


def list_compensation_attempts(
    factory: sessionmaker[Session], compensation_id: OpaqueId
) -> list[CompensationAttempt]:
    with unit_of_work(factory) as uow:
        return uow.compensation_attempts.list_for_compensation(compensation_id)


def list_execution_attempts(
    factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[ExecutionAttempt]:
    with unit_of_work(factory) as uow:
        return uow.attempts.list_for_operation(operation_id)


def load_policy(
    factory: sessionmaker[Session], operation: Operation
) -> PolicyDecision | None:
    if operation.current_policy_decision_id is None:
        return None
    with unit_of_work(factory) as uow:
        return uow.policy_decisions.get(operation.current_policy_decision_id)


def get_verification(
    factory: sessionmaker[Session], verification_id: OpaqueId
) -> tuple[VerificationRequest, VerificationResult | None] | None:
    with unit_of_work(factory) as uow:
        return uow.verifications.get(verification_id)


def list_verifications(
    factory: sessionmaker[Session], operation_id: OpaqueId
) -> list[tuple[VerificationRequest, VerificationResult | None]]:
    with unit_of_work(factory) as uow:
        return uow.verifications.list_for_operation(operation_id)
