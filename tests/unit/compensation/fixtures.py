from __future__ import annotations

from dataclasses import replace

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.capability import CompensationEvidence, VerificationEvidence
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    INITIAL_COMPENSATION_VERSION,
    ArgumentsMode,
    AttemptState,
    CompensationKind,
    CompensationState,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    OperationState,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.intent import (
    compensation_idempotency_identity,
    operation_idempotency_identity,
)
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyObligations
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.policy.evaluation import PHASE5_DEFAULT_OBLIGATIONS
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from tests.unit.domain.fixtures import (
    ATTEMPT_ID,
    COMP_ATTEMPT_ID,
    COMP_ID,
    LATER,
    OP_ID,
    REQUESTER,
    RISK,
    TS,
    VERIFY_ID,
    make_intent,
)

CLOCK = FixedClock(TS)
DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY]


def obligations_with(
    *,
    require_verification: bool = False,
    automatic_compensation_allowed: bool = False,
    max_automatic_execution_attempts: int | None = 1,
    max_automatic_recovery_attempts: int | None = None,
) -> PolicyObligations:
    return replace(
        PHASE5_DEFAULT_OBLIGATIONS,
        require_verification=require_verification,
        automatic_compensation_allowed=automatic_compensation_allowed,
        max_automatic_execution_attempts=max_automatic_execution_attempts,
        max_automatic_recovery_attempts=max_automatic_recovery_attempts,
    )


def make_provider_evidence() -> ProviderEvidence:
    return ProviderEvidence(
        source=EvidenceSource.OPERATION_LOOKUP,
        provider="stateback.reference",
        observed_at=CLOCK.now(),
        provider_status="applied",
        provider_request_id=None,
        external_operation_id=None,
        external_resource_ids=(),
        evidence_fields=json_from_plain({}),
        raw_reference=None,
    )


def make_error(*, kind: ErrorKind, code: str) -> NormalizedError:
    return NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=kind,
        code=code,
        message="compensation error",
        retryable_infrastructure=kind is ErrorKind.TRANSIENT_TRANSPORT,
        provider_http_status=None,
        provider_error_code=None,
        retry_after_seconds=None,
        details=json_from_plain({}),
    )


def make_operation(
    *,
    state: OperationState = OperationState.SUCCEEDED,
    version: int = 2,
) -> Operation:
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=state,
        version=version,
        intent=make_intent(),
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=ATTEMPT_ID,
        latest_verification_id=None,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )


def make_execution_attempt(
    *,
    state: AttemptState = AttemptState.COMPLETED,
    outcome: EffectOutcome | None = EffectOutcome.APPLIED,
    attempt_number: int = 1,
    external_operation_id: str | None = "ext-1",
    external_resource_ids: tuple[str, ...] = (),
    error: NormalizedError | None = None,
) -> ExecutionAttempt:
    completed = state is AttemptState.COMPLETED
    evidence = (
        replace(make_provider_evidence(), external_resource_ids=external_resource_ids)
        if completed and external_resource_ids
        else None
    )
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=ATTEMPT_ID,
        operation_id=OP_ID,
        attempt_number=attempt_number,
        state=state,
        started_at=TS,
        completed_at=LATER if completed else None,
        provider_idempotency_key="key-1",
        external_operation_id=external_operation_id if completed else None,
        external_resource_ids=external_resource_ids,
        outcome=outcome if completed else None,
        evidence=evidence,
        error=error if completed else None,
        correlation_id=None,
    )


def make_compensation(
    *,
    kind: CompensationKind = CompensationKind.EXACT,
    state: CompensationState = CompensationState.PENDING,
    version: int = INITIAL_COMPENSATION_VERSION,
) -> Compensation:
    return Compensation(
        contract_version=CONTRACT_VERSION,
        compensation_id=COMP_ID,
        original_operation_id=OP_ID,
        kind=kind,
        state=state,
        version=version,
        intent_digest="a" * 64,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain({"reason": "undo"}),
        arguments_ref=None,
        idempotency_identity=compensation_idempotency_identity(COMP_ID),
        requested_by=REQUESTER,
        policy_decision_id=None,
        created_at=TS,
        updated_at=TS,
    )


def make_compensation_attempt(
    *,
    state: AttemptState = AttemptState.COMPLETED,
    outcome: EffectOutcome | None = EffectOutcome.APPLIED,
    attempt_number: int = 1,
    error: NormalizedError | None = None,
) -> CompensationAttempt:
    completed = state is AttemptState.COMPLETED
    return CompensationAttempt(
        contract_version=CONTRACT_VERSION,
        compensation_attempt_id=COMP_ATTEMPT_ID,
        compensation_id=COMP_ID,
        attempt_number=attempt_number,
        state=state,
        started_at=TS,
        completed_at=LATER if completed else None,
        provider_idempotency_key="key-1",
        external_operation_id=None,
        outcome=outcome if completed else None,
        evidence=None,
        error=error if completed else None,
    )


def make_compensation_evidence(
    *,
    outcome: EffectOutcome = EffectOutcome.APPLIED,
    error: NormalizedError | None = None,
) -> CompensationEvidence:
    return CompensationEvidence(
        outcome=outcome, evidence=None, error=error, external_operation_id=None
    )


def make_verification_evidence(
    *,
    outcome: EffectOutcome = EffectOutcome.APPLIED,
    error: NormalizedError | None = None,
) -> VerificationEvidence:
    return VerificationEvidence(
        outcome=outcome, evidence=make_provider_evidence(), error=error
    )


def make_verification_request() -> VerificationRequest:
    from stateback.domain.enums import VerificationTarget

    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OP_ID,
        operation_version=2,
        target=VerificationTarget.COMPENSATION,
        target_attempt_id=COMP_ATTEMPT_ID,
        effect=EFFECT_MUTATE_PROVIDER_KEY,
        external_operation_id=None,
        external_resource_ids=(),
        idempotency_identity=compensation_idempotency_identity(COMP_ID),
        provider_evidence_refs=(),
        requested_at=TS,
    )


def make_verification_result(
    *,
    outcome: EffectOutcome,
    error: NormalizedError | None = None,
) -> VerificationResult:
    return VerificationResult(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        outcome=outcome,
        evidence=make_provider_evidence(),
        error=error,
        completed_at=LATER,
    )
