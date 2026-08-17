"""Build ORIGINAL_EFFECT VerificationRequest from a durable operation."""

from __future__ import annotations

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.enums import CONTRACT_VERSION, VerificationTarget
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest


def build_original_verification_request(
    *,
    operation: Operation,
    attempt: ExecutionAttempt | None,
    verification_id: OpaqueId,
    requested_at: UtcTimestamp,
) -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=verification_id,
        operation_id=operation.operation_id,
        operation_version=operation.version,
        target=VerificationTarget.ORIGINAL_EFFECT,
        target_attempt_id=None if attempt is None else attempt.attempt_id,
        effect=operation.intent.effect,
        external_operation_id=(
            None if attempt is None else attempt.external_operation_id
        ),
        external_resource_ids=() if attempt is None else attempt.external_resource_ids,
        idempotency_identity=operation.idempotency_identity,
        provider_evidence_refs=(),
        requested_at=requested_at,
    )
