"""Pure eligibility rules for starting a compensation. No I/O."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import EffectDescriptor
from stateback.domain.compensation import CompensationAttempt
from stateback.domain.enums import (
    AttemptState,
    CompensationKind,
    EffectOutcome,
    ErrorKind,
    OperationState,
)
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyObligations
from stateback.transitions.kinds import TransitionKind

_FAILED_WITHOUT_ARTIFACT_ERROR_KINDS = frozenset(
    {ErrorKind.VALIDATION, ErrorKind.UNSUPPORTED_CAPABILITY}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class EligibilityDecision:
    allowed: bool
    start_kind: TransitionKind | None
    reason_code: str


def has_external_artifact(
    attempt: ExecutionAttempt | CompensationAttempt | None,
) -> bool:
    if attempt is None:
        return False
    if attempt.external_operation_id:
        return True
    evidence = attempt.evidence
    if evidence is None:
        return False
    if evidence.external_operation_id:
        return True
    return len(evidence.external_resource_ids) > 0


def evaluate_start_eligibility(
    *,
    operation: Operation,
    descriptor: EffectDescriptor,
    obligations: PolicyObligations,
    latest_original_attempt: ExecutionAttempt | None,
    automatic: bool,
    operator: bool,
) -> EligibilityDecision:
    if descriptor.compensation_kind is CompensationKind.NONE:
        return EligibilityDecision(
            allowed=False, start_kind=None, reason_code="compensation_kind_none"
        )
    if (
        operation.state is OperationState.SUCCEEDED
        and automatic
        and not obligations.automatic_compensation_allowed
    ):
        return EligibilityDecision(
            allowed=False,
            start_kind=None,
            reason_code="automatic_compensation_forbidden",
        )
    if (
        operation.state is OperationState.FAILED
        and automatic
        and not obligations.automatic_compensation_allowed
    ):
        return EligibilityDecision(
            allowed=False,
            start_kind=None,
            reason_code="automatic_compensation_forbidden",
        )
    if operation.state is OperationState.SUCCEEDED:
        return EligibilityDecision(
            allowed=True,
            start_kind=TransitionKind.SUCCEEDED_START_COMPENSATION,
            reason_code="accepted",
        )
    if operation.state is OperationState.FAILED:
        if not has_external_artifact(latest_original_attempt):
            return EligibilityDecision(
                allowed=False, start_kind=None, reason_code="failed_without_artifact"
            )
        attempt = latest_original_attempt
        if (
            attempt is not None
            and attempt.state is AttemptState.COMPLETED
            and attempt.outcome is EffectOutcome.NOT_APPLIED
            and attempt.error is not None
            and attempt.error.kind in _FAILED_WITHOUT_ARTIFACT_ERROR_KINDS
        ):
            return EligibilityDecision(
                allowed=False, start_kind=None, reason_code="failed_without_artifact"
            )
        return EligibilityDecision(
            allowed=True,
            start_kind=TransitionKind.FAILED_START_COMPENSATION,
            reason_code="accepted",
        )
    if operation.state is OperationState.MANUAL_INTERVENTION:
        if operator:
            return EligibilityDecision(
                allowed=True,
                start_kind=TransitionKind.MANUAL_START_COMPENSATION,
                reason_code="accepted",
            )
        return EligibilityDecision(
            allowed=False, start_kind=None, reason_code="actor_required"
        )
    return EligibilityDecision(
        allowed=False, start_kind=None, reason_code="source_state_mismatch"
    )
