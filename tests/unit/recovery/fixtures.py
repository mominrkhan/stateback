from __future__ import annotations

from dataclasses import replace

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.enums import (
    CONTRACT_VERSION,
    AttemptState,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    OperationState,
    VerificationTarget,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import operation_idempotency_identity
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.operation import Operation
from stateback.domain.policy import PolicyObligations
from stateback.domain.reconciliation import ReconciliationInput
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.policy.evaluation import PHASE5_DEFAULT_OBLIGATIONS
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.effects import (
    EFFECT_MUTATE_PROVIDER_KEY,
    REFERENCE_DESCRIPTORS,
)
from tests.unit.domain.fixtures import (
    ATTEMPT_ID,
    LATER,
    OP_ID,
    RISK,
    TS,
    VERIFY_ID,
    make_intent,
)

CLOCK = FixedClock(TS)
DESCRIPTOR = REFERENCE_DESCRIPTORS[EFFECT_MUTATE_PROVIDER_KEY]


def make_error(
    *,
    kind: ErrorKind,
    code: str,
) -> NormalizedError:
    return NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=kind,
        code=code,
        message="verification error",
        retryable_infrastructure=kind is ErrorKind.TRANSIENT_TRANSPORT,
        provider_http_status=None,
        provider_error_code=None,
        retry_after_seconds=None,
        details=json_from_plain({}),
    )


def make_evidence() -> ProviderEvidence:
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


def make_operation(
    *,
    state: OperationState = OperationState.VERIFYING,
    version: int = 3,
    latest_attempt_id: OpaqueId | None = ATTEMPT_ID,
    latest_verification_id: OpaqueId | None = VERIFY_ID,
) -> Operation:
    intent = make_intent()
    return Operation(
        contract_version=CONTRACT_VERSION,
        operation_id=OP_ID,
        state=state,
        version=version,
        intent=intent,
        risk_level=RISK,
        idempotency_identity=operation_idempotency_identity(OP_ID),
        current_policy_decision_id=None,
        current_approval_id=None,
        latest_attempt_id=latest_attempt_id,
        latest_verification_id=latest_verification_id,
        compensation_id=None,
        created_at=TS,
        updated_at=TS,
    )


def make_attempt(
    *,
    state: AttemptState = AttemptState.COMPLETED,
    outcome: EffectOutcome | None = EffectOutcome.UNKNOWN,
    attempt_number: int = 1,
    external_operation_id: str | None = None,
    external_resource_ids: tuple[str, ...] = (),
) -> ExecutionAttempt:
    completed = state is AttemptState.COMPLETED
    return ExecutionAttempt(
        contract_version=CONTRACT_VERSION,
        attempt_id=ATTEMPT_ID,
        operation_id=OP_ID,
        attempt_number=attempt_number,
        state=state,
        started_at=TS,
        completed_at=LATER if completed else None,
        provider_idempotency_key="key-1",
        external_operation_id=external_operation_id,
        external_resource_ids=external_resource_ids,
        outcome=outcome if completed else None,
        evidence=None,
        error=None,
        correlation_id=None,
    )


def make_verification_result(
    *,
    outcome: EffectOutcome,
    error: NormalizedError | None = None,
    verification_id: OpaqueId = VERIFY_ID,
) -> VerificationResult:
    return VerificationResult(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        outcome=outcome,
        evidence=make_evidence(),
        error=error,
        completed_at=LATER,
    )


def make_verification_request(
    *,
    target: VerificationTarget = VerificationTarget.ORIGINAL_EFFECT,
) -> VerificationRequest:
    operation = make_operation()
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OP_ID,
        operation_version=operation.version,
        target=target,
        target_attempt_id=ATTEMPT_ID,
        effect=operation.intent.effect,
        external_operation_id=None,
        external_resource_ids=(),
        idempotency_identity=operation.idempotency_identity,
        provider_evidence_refs=(),
        requested_at=TS,
    )


def make_input(
    *,
    outcome: EffectOutcome,
    error: NormalizedError | None = None,
    attempt_outcome: EffectOutcome | None = EffectOutcome.UNKNOWN,
    attempt_state: AttemptState = AttemptState.COMPLETED,
    attempt_number: int = 1,
    obligations: PolicyObligations | None = None,
) -> ReconciliationInput:
    return ReconciliationInput(
        operation=make_operation(),
        attempts=(
            make_attempt(
                state=attempt_state,
                outcome=attempt_outcome,
                attempt_number=attempt_number,
            ),
        ),
        verification_result=make_verification_result(outcome=outcome, error=error),
        provider_descriptor=DESCRIPTOR,
        policy_obligations=(
            PHASE5_DEFAULT_OBLIGATIONS if obligations is None else obligations
        ),
    )


def obligations_with(
    *,
    max_automatic_execution_attempts: int | None = 1,
    max_automatic_recovery_attempts: int | None = None,
) -> PolicyObligations:
    return replace(
        PHASE5_DEFAULT_OBLIGATIONS,
        max_automatic_execution_attempts=max_automatic_execution_attempts,
        max_automatic_recovery_attempts=max_automatic_recovery_attempts,
    )
