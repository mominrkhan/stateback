from __future__ import annotations

import pytest

from stateback.domain.enums import CONTRACT_VERSION, ErrorKind, EvidenceSource
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonObject, json_from_plain
from stateback.providers.normalize import evidence_for_unclassified_exception
from tests.unit.providers.fixtures import TS

pytestmark = pytest.mark.unit


def test_evidence_fields_reject_authorization_header_payload() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ProviderEvidence(
            source=EvidenceSource.EXECUTION_RESPONSE,
            provider="stateback.reference",
            observed_at=TS,
            provider_status="applied",
            provider_request_id=None,
            external_operation_id=None,
            external_resource_ids=(),
            evidence_fields=json_from_plain({"authorization": "Bearer secret"}),
            raw_reference=None,
        )
    assert exc.value.reason_code == "secret_field"


def test_unclassified_details_have_no_secret_keys() -> None:
    _, error, _ = evidence_for_unclassified_exception(
        exc=RuntimeError("token=super-secret"),
        observed_at=TS,
        provider="stateback.reference",
    )
    details = error.details
    assert isinstance(details, JsonObject)
    keys = {key for key, _ in details.items}
    assert keys == {"exception_type"}
    assert "token" not in keys
    assert "authorization" not in keys
    assert "super-secret" not in error.message


def test_error_details_only_exception_type() -> None:
    error = NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=ErrorKind.INTERNAL,
        code="ref.internal.unclassified",
        message="unclassified adapter exception",
        retryable_infrastructure=False,
        provider_http_status=None,
        provider_error_code=None,
        retry_after_seconds=None,
        details=json_from_plain({"exception_type": "RuntimeError"}),
    )
    details = error.details
    assert isinstance(details, JsonObject)
    assert details.as_dict() == {"exception_type": "RuntimeError"}
