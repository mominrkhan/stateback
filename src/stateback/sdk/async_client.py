"""Async typed client with cancellation-safe polling."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from stateback.sdk.client import (
    StatebackTransportError,
    client_error_from_response,
    operation_status_from_payload,
)
from stateback.sdk.models import OperationStatus, WaitOutcome, WaitResult


@dataclass(frozen=True, slots=True)
class AsyncOperationHandle:
    _client: AsyncStatebackClient
    operation_id: str
    initial_status: OperationStatus

    async def status(self) -> OperationStatus:
        return await self._client.get_operation(self.operation_id)

    async def audit(
        self, *, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        return await self._client.get_audit(
            self.operation_id, after_sequence=after_sequence, limit=limit
        )

    async def wait(self, *, timeout: float, poll_interval: float = 0.25) -> WaitResult:
        if timeout < 0 or poll_interval <= 0:
            raise ValueError("timeout must be >= 0 and poll_interval must be > 0")
        deadline = time.monotonic() + timeout
        delay = poll_interval
        current = await self.status()
        while not current.is_forward_terminal:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return WaitResult(outcome=WaitOutcome.TIMED_OUT, operation=current)
            await asyncio.sleep(min(delay, remaining))
            current = await self.status()
            delay = min(delay * 1.5, 5.0)
        return WaitResult(outcome=WaitOutcome.COMPLETED, operation=current)


class AsyncStatebackClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncStatebackClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def submit(
        self,
        *,
        effect: dict[str, str],
        arguments: object,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
        deployment_environment: str = "production",
        correlation_id: str | None = None,
    ) -> AsyncOperationHandle:
        if not idempotency_key:
            raise ValueError(
                "idempotency_key must be non-empty and stable across retries"
            )
        headers = {"Idempotency-Key": idempotency_key}
        if correlation_id is not None:
            headers["X-Correlation-ID"] = correlation_id
        payload = await self._request(
            "POST",
            "/v1/operations",
            headers=headers,
            json={
                "contract_version": "v1",
                "effect": effect,
                "arguments": arguments,
                "metadata": metadata or {},
                "deployment_environment": deployment_environment,
            },
        )
        operation = operation_status_from_payload(payload)
        return AsyncOperationHandle(self, operation.operation_id, operation)

    async def get_operation(self, operation_id: str) -> OperationStatus:
        return operation_status_from_payload(
            await self._request("GET", f"/v1/operations/{operation_id}")
        )

    async def get_audit(
        self, operation_id: str, *, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/v1/operations/{operation_id}/audit",
            params={"after_sequence": after_sequence, "limit": limit},
        )
        if not isinstance(payload, dict) or payload.get("contract_version") != "v1":
            raise StatebackTransportError("malformed_response")
        return payload

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> object:
        try:
            response = await self._http.request(
                method, path, headers=headers, json=json, params=params
            )
        except httpx.HTTPError as exc:
            raise StatebackTransportError("transport_failed") from exc
        if response.is_success:
            try:
                return response.json()
            except ValueError as exc:
                raise StatebackTransportError("malformed_response") from exc
        raise client_error_from_response(response)
