from __future__ import annotations

import pytest

from stateback.domain.capability import (
    EffectDescriptor,
    ProviderKeySemantics,
    ValidationResult,
)
from stateback.domain.enums import (
    CONTRACT_VERSION,
    CompensationKind,
    ErrorKind,
    IdempotencyMode,
    Mutability,
    RiskLevel,
    VerificationMode,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import json_from_plain
from tests.unit.domain.fixtures import EFFECT

pytestmark = pytest.mark.unit


def test_provider_key_requires_semantics() -> None:
    with pytest.raises(ContractValidationError) as exc:
        EffectDescriptor(
            contract_version=CONTRACT_VERSION,
            effect=EFFECT,
            mutability=Mutability.MUTATING,
            risk_level=RiskLevel.HIGH,
            idempotency_mode=IdempotencyMode.PROVIDER_KEY,
            verification_mode=VerificationMode.OPERATION_LOOKUP,
            compensation_kind=CompensationKind.EXACT,
            supports_external_operation_id=True,
            immediate_response_can_prove_applied=True,
            immediate_response_can_prove_not_applied=True,
            provider_key_semantics=None,
            documentation="docs",
        )
    assert exc.value.reason_code == "illegal_combination"


def test_read_only_cannot_declare_compensation() -> None:
    with pytest.raises(ContractValidationError) as exc:
        EffectDescriptor(
            contract_version=CONTRACT_VERSION,
            effect=EFFECT,
            mutability=Mutability.READ_ONLY,
            risk_level=RiskLevel.LOW,
            idempotency_mode=IdempotencyMode.NATURAL,
            verification_mode=VerificationMode.READ_BACK,
            compensation_kind=CompensationKind.EXACT,
            supports_external_operation_id=False,
            immediate_response_can_prove_applied=False,
            immediate_response_can_prove_not_applied=True,
            provider_key_semantics=None,
            documentation="docs",
        )
    assert exc.value.reason_code == "illegal_combination"


def test_none_idempotency_forbids_key_semantics() -> None:
    with pytest.raises(ContractValidationError) as exc:
        EffectDescriptor(
            contract_version=CONTRACT_VERSION,
            effect=EFFECT,
            mutability=Mutability.MUTATING,
            risk_level=RiskLevel.HIGH,
            idempotency_mode=IdempotencyMode.NONE,
            verification_mode=VerificationMode.NONE,
            compensation_kind=CompensationKind.NONE,
            supports_external_operation_id=False,
            immediate_response_can_prove_applied=False,
            immediate_response_can_prove_not_applied=False,
            provider_key_semantics=ProviderKeySemantics(
                scope="account",
                replay_window="24h",
                same_key_same_request_required=True,
                conflicting_request_behavior="reject",
                response_replay_behavior="replay",
            ),
            documentation="docs",
        )
    assert exc.value.reason_code == "illegal_combination"


def _error(*, kind: ErrorKind) -> NormalizedError:
    return NormalizedError(
        contract_version=CONTRACT_VERSION,
        kind=kind,
        code="test.validation",
        message="invalid",
        retryable_infrastructure=False,
        provider_http_status=None,
        provider_error_code=None,
        retry_after_seconds=None,
        details=json_from_plain({}),
    )


def test_validation_result_accepted_rejects_error() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ValidationResult(accepted=True, error=_error(kind=ErrorKind.VALIDATION))
    assert exc.value.reason_code == "illegal_combination"


def test_validation_result_rejected_requires_error() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ValidationResult(accepted=False, error=None)
    assert exc.value.reason_code == "illegal_combination"


def test_validation_result_rejects_persistence_kind() -> None:
    with pytest.raises(ContractValidationError) as exc:
        ValidationResult(accepted=False, error=_error(kind=ErrorKind.PERSISTENCE))
    assert exc.value.reason_code == "illegal_combination"
