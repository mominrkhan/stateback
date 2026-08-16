"""Process-local fake-external store. Not crash-durable. No delete."""

from __future__ import annotations

from dataclasses import dataclass

from stateback.domain.exceptions import ContractValidationError
from stateback.domain.time import UtcTimestamp


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceResource:
    resource_id: str
    action: str
    external_operation_id: str
    provider_idempotency_key: str | None
    arguments_fingerprint: str
    applied: bool
    compensated: bool
    mitigated: bool
    created_at: UtcTimestamp


class ReferenceStore:
    def __init__(self) -> None:
        self._by_resource_id: dict[str, ReferenceResource] = {}
        self._by_external_operation_id: dict[str, ReferenceResource] = {}
        self._by_provider_key: dict[str, ReferenceResource] = {}
        self._all: list[ReferenceResource] = []

    def get_by_resource_id(self, resource_id: str) -> ReferenceResource | None:
        return self._by_resource_id.get(resource_id)

    def get_by_external_operation_id(
        self, external_operation_id: str
    ) -> ReferenceResource | None:
        return self._by_external_operation_id.get(external_operation_id)

    def get_by_provider_key(
        self, provider_idempotency_key: str
    ) -> ReferenceResource | None:
        return self._by_provider_key.get(provider_idempotency_key)

    def put(self, resource: ReferenceResource) -> None:
        if resource.resource_id in self._by_resource_id:
            raise ContractValidationError(
                "duplicate_key",
                "ReferenceStore.put refuses an existing resource_id",
            )
        self._index(resource)
        self._all.append(resource)

    def replace(self, resource: ReferenceResource) -> None:
        existing = self._by_resource_id.get(resource.resource_id)
        if existing is None:
            raise ContractValidationError(
                "illegal_combination",
                "ReferenceStore.replace requires an existing resource_id",
            )
        self._drop_indexes(existing)
        self._index(resource)
        self._all = [
            resource if item.resource_id == resource.resource_id else item
            for item in self._all
        ]

    def all_resources(self) -> tuple[ReferenceResource, ...]:
        return tuple(self._all)

    def _index(self, resource: ReferenceResource) -> None:
        self._by_resource_id[resource.resource_id] = resource
        self._by_external_operation_id[resource.external_operation_id] = resource
        if resource.provider_idempotency_key is not None:
            self._by_provider_key[resource.provider_idempotency_key] = resource

    def _drop_indexes(self, resource: ReferenceResource) -> None:
        self._by_resource_id.pop(resource.resource_id, None)
        self._by_external_operation_id.pop(resource.external_operation_id, None)
        if resource.provider_idempotency_key is not None:
            current = self._by_provider_key.get(resource.provider_idempotency_key)
            if current is resource or (
                current is not None and current.resource_id == resource.resource_id
            ):
                self._by_provider_key.pop(resource.provider_idempotency_key, None)
