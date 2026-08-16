from __future__ import annotations

from datetime import UTC, datetime

from stateback.domain.capability import (
    CompensationRequest,
    ProviderExecutionContext,
    ProviderExecutionRequest,
)
from stateback.domain.enums import CONTRACT_VERSION, VerificationTarget
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.ids import OpaqueId
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef
from stateback.domain.time import UtcTimestamp
from stateback.domain.verification import VerificationRequest
from stateback.providers.reference.adapter import ReferenceAdapter
from stateback.providers.reference.clock import FixedClock
from stateback.providers.reference.store import ReferenceStore

TS = UtcTimestamp(value=datetime(2026, 8, 16, 22, 0, 0, tzinfo=UTC))
OP_ID = OpaqueId(value="00000000-0000-4000-8000-000000000011")
ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-000000000012")
VERIFY_ID = OpaqueId(value="00000000-0000-4000-8000-000000000013")
COMP_ID = OpaqueId(value="00000000-0000-4000-8000-000000000014")
COMP_ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-000000000015")


def make_context(
    *,
    effect_key: str | None = "key-1",
    deadline: UtcTimestamp | None = None,
    attempt_id: OpaqueId | None = None,
) -> ProviderExecutionContext:
    return ProviderExecutionContext(
        operation_id=OP_ID,
        attempt_id=ATTEMPT_ID if attempt_id is None else attempt_id,
        idempotency_identity="sb:v1:op:" + OP_ID.value,
        provider_idempotency_key=effect_key,
        correlation_id=None,
        deadline=deadline,
    )


def make_request(
    effect: EffectRef, resource_id: str = "res-1"
) -> ProviderExecutionRequest:
    return ProviderExecutionRequest(
        effect=effect,
        arguments=json_from_plain({"resource_id": resource_id}),
    )


def make_adapter(
    *, visibility_delay_seconds: int = 0
) -> tuple[ReferenceAdapter, ReferenceStore, FixedClock]:
    store = ReferenceStore()
    clock = FixedClock(TS)
    adapter = ReferenceAdapter(
        store=store,
        clock=clock,
        visibility_delay_seconds=visibility_delay_seconds,
    )
    return adapter, store, clock


def make_verify_request(
    effect: EffectRef,
    *,
    target: VerificationTarget = VerificationTarget.ORIGINAL_EFFECT,
    external_operation_id: str | None = None,
    external_resource_ids: tuple[str, ...] = (),
) -> VerificationRequest:
    return VerificationRequest(
        contract_version=CONTRACT_VERSION,
        verification_id=VERIFY_ID,
        operation_id=OP_ID,
        operation_version=1,
        target=target,
        target_attempt_id=ATTEMPT_ID,
        effect=effect,
        external_operation_id=external_operation_id,
        external_resource_ids=external_resource_ids,
        idempotency_identity="sb:v1:op:" + OP_ID.value,
        provider_evidence_refs=(),
        requested_at=TS,
    )


def make_compensate_request(
    *,
    resource_id: str = "res-1",
    provider_idempotency_key: str | None = "key-1",
    original_evidence: tuple[ProviderEvidence, ...] = (),
) -> CompensationRequest:
    return CompensationRequest(
        original_operation_id=OP_ID,
        compensation_id=COMP_ID,
        compensation_attempt_id=COMP_ATTEMPT_ID,
        original_evidence=original_evidence,
        compensation_arguments=json_from_plain({"resource_id": resource_id}),
        idempotency_identity="sb:v1:comp:" + COMP_ID.value,
        provider_idempotency_key=provider_idempotency_key,
    )
