"""ProviderEvidence — `contracts/OPERATION_CONTRACT.md` §8."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.enums import EvidenceSource
from stateback.domain.jsonutil import JsonValue, json_to_plain, parse_json_value
from stateback.domain.secrets import reject_secrets_in_json
from stateback.domain.time import UtcTimestamp
from stateback.domain.wire import (
    optional_key,
    parse_enum,
    parse_optional_str,
    parse_str,
    parse_str_list,
    reject_unknown_keys,
    require_key,
    require_mapping,
)

_FIELDS = frozenset(
    {
        "source",
        "provider",
        "observed_at",
        "provider_status",
        "provider_request_id",
        "external_operation_id",
        "external_resource_ids",
        "evidence_fields",
        "raw_reference",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderEvidence:
    source: EvidenceSource
    provider: str
    observed_at: UtcTimestamp
    provider_status: str | None
    provider_request_id: str | None
    external_operation_id: str | None
    external_resource_ids: tuple[str, ...]
    evidence_fields: JsonValue
    raw_reference: str | None

    def __post_init__(self) -> None:
        reject_secrets_in_json(
            self.evidence_fields, field="ProviderEvidence.evidence_fields"
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "source": self.source.value,
            "provider": self.provider,
            "observed_at": self.observed_at.to_wire(),
            "provider_status": self.provider_status,
            "provider_request_id": self.provider_request_id,
            "external_operation_id": self.external_operation_id,
            "external_resource_ids": list(self.external_resource_ids),
            "evidence_fields": json_to_plain(self.evidence_fields),
            "raw_reference": self.raw_reference,
        }

    @classmethod
    def from_wire(cls, raw: object) -> ProviderEvidence:
        data = require_mapping(raw, type_name="ProviderEvidence")
        reject_unknown_keys(data, _FIELDS, type_name="ProviderEvidence")
        return cls(
            source=parse_enum(
                EvidenceSource,
                require_key(data, "source", type_name="ProviderEvidence"),
                field="ProviderEvidence.source",
            ),
            provider=parse_str(
                require_key(data, "provider", type_name="ProviderEvidence"),
                field="ProviderEvidence.provider",
            ),
            observed_at=UtcTimestamp.from_wire(
                require_key(data, "observed_at", type_name="ProviderEvidence"),
                field="ProviderEvidence.observed_at",
            ),
            provider_status=parse_optional_str(
                optional_key(data, "provider_status"),
                field="ProviderEvidence.provider_status",
            ),
            provider_request_id=parse_optional_str(
                optional_key(data, "provider_request_id"),
                field="ProviderEvidence.provider_request_id",
            ),
            external_operation_id=parse_optional_str(
                optional_key(data, "external_operation_id"),
                field="ProviderEvidence.external_operation_id",
            ),
            external_resource_ids=parse_str_list(
                require_key(
                    data, "external_resource_ids", type_name="ProviderEvidence"
                ),
                field="ProviderEvidence.external_resource_ids",
            ),
            evidence_fields=parse_json_value(
                require_key(data, "evidence_fields", type_name="ProviderEvidence"),
                field="ProviderEvidence.evidence_fields",
            ),
            raw_reference=parse_optional_str(
                optional_key(data, "raw_reference"),
                field="ProviderEvidence.raw_reference",
            ),
        )


def parse_optional_evidence(raw: object) -> ProviderEvidence | None:
    if raw is None:
        return None
    return ProviderEvidence.from_wire(raw)
