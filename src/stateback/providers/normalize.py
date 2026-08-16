"""Normalize unclassified adapter exceptions into UNKNOWN + INTERNAL."""

from __future__ import annotations

from stateback.domain.enums import (
    CONTRACT_VERSION,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.time import UtcTimestamp


def evidence_for_unclassified_exception(
    *,
    exc: Exception,
    observed_at: UtcTimestamp,
    provider: str,
) -> tuple[EffectOutcome, NormalizedError, ProviderEvidence]:
    error = NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=ErrorKind.INTERNAL,
        code="ref.internal.unclassified",
        message="unclassified adapter exception",
        retryable_infrastructure=False,
        provider_http_status=None,
        provider_error_code=None,
        retry_after_seconds=None,
        details=json_from_plain({"exception_type": type(exc).__name__}),
    )
    evidence = ProviderEvidence(
        source=EvidenceSource.EXECUTION_RESPONSE,
        provider=provider,
        observed_at=observed_at,
        provider_status=None,
        provider_request_id=None,
        external_operation_id=None,
        external_resource_ids=(),
        evidence_fields=json_from_plain({}),
        raw_reference=None,
    )
    return (EffectOutcome.UNKNOWN, error, evidence)
