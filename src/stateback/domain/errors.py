"""NormalizedError — `contracts/ERROR_CONTRACT.md`."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import CONTRACT_VERSION, ErrorKind
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.jsonutil import JsonValue, json_to_plain, parse_json_value
from stateback.domain.secrets import reject_secrets_in_json
from stateback.domain.wire import (
    optional_key,
    parse_bool,
    parse_contract_version,
    parse_enum,
    parse_optional_int,
    parse_optional_str,
    parse_str,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_FIELDS = frozenset(
    {
        "contract_version",
        "kind",
        "code",
        "message",
        "retryable_infrastructure",
        "provider_http_status",
        "provider_error_code",
        "retry_after_seconds",
        "details",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NormalizedError:
    contract_version: str
    kind: ErrorKind
    code: str
    message: str
    retryable_infrastructure: bool
    provider_http_status: int | None
    provider_error_code: str | None
    retry_after_seconds: int | None
    details: JsonValue

    def __post_init__(self) -> None:
        if self.contract_version != CONTRACT_VERSION:
            raise ContractValidationError(
                "unsupported_contract_version",
                "NormalizedError.contract_version must be v1",
            )
        if self.provider_http_status is not None and not (
            100 <= self.provider_http_status <= 599
        ):
            raise ContractValidationError(
                "invalid_range",
                "provider_http_status must be in 100..599",
            )
        reject_secrets_in_json(self.details, field="NormalizedError.details")

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "kind": self.kind.value,
            "code": self.code,
            "message": self.message,
            "retryable_infrastructure": self.retryable_infrastructure,
            "provider_http_status": self.provider_http_status,
            "provider_error_code": self.provider_error_code,
            "retry_after_seconds": self.retry_after_seconds,
            "details": json_to_plain(self.details),
        }

    @classmethod
    def from_wire(cls, raw: object) -> NormalizedError:
        data = require_mapping(raw, type_name="NormalizedError")
        reject_unknown_keys(data, _FIELDS, type_name="NormalizedError")
        parse_contract_version(
            require_key(data, "contract_version", type_name="NormalizedError"),
            type_name="NormalizedError",
        )
        return cls(
            contract_version=CONTRACT_VERSION,
            kind=parse_enum(
                ErrorKind,
                require_key(data, "kind", type_name="NormalizedError"),
                field="NormalizedError.kind",
            ),
            code=parse_str(
                require_key(data, "code", type_name="NormalizedError"),
                field="NormalizedError.code",
            ),
            message=parse_str(
                require_key(data, "message", type_name="NormalizedError"),
                field="NormalizedError.message",
            ),
            retryable_infrastructure=parse_bool(
                require_key(
                    data, "retryable_infrastructure", type_name="NormalizedError"
                ),
                field="NormalizedError.retryable_infrastructure",
            ),
            provider_http_status=parse_optional_int(
                optional_key(data, "provider_http_status"),
                field="NormalizedError.provider_http_status",
                minimum=100,
            ),
            provider_error_code=parse_optional_str(
                optional_key(data, "provider_error_code"),
                field="NormalizedError.provider_error_code",
            ),
            retry_after_seconds=parse_optional_int(
                optional_key(data, "retry_after_seconds"),
                field="NormalizedError.retry_after_seconds",
                minimum=0,
            ),
            details=parse_json_value(
                require_key(data, "details", type_name="NormalizedError"),
                field="NormalizedError.details",
            ),
        )


def parse_optional_error(raw: object) -> NormalizedError | None:
    if raw is None:
        return None
    return NormalizedError.from_wire(raw)
