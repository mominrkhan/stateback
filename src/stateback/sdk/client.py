"""Synchronous typed client; transport failures never become operation states."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from stateback.sdk.models import OperationStatus, WaitOutcome, WaitResult


class StatebackClientError(Exception):
    def __init__(self, code: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class StatebackTransportError(Exception):
    """No durable operation conclusion can be inferred from this exception."""


@dataclass(frozen=True, slots=True)
class OperationHandle:
    _client: StatebackClient
    operation_id: str

    def status(self) -> OperationStatus:
        return self._client.get_operation(self.operation_id)

    def audit(self, *, after_sequence: int = 0, limit: int = 50) -> dict[str, Any]:
        return self._client.get_audit(
            self.operation_id, after_sequence=after_sequence, limit=limit
        )

    def wait(
        self,
        *,
        timeout: float,
        poll_interval: float = 0.25,
        cancel: threading.Event | None = None,
    ) -> WaitResult:
        if timeout < 0 or poll_interval <= 0:
            raise ValueError("timeout must be >= 0 and poll_interval must be > 0")
        deadline = time.monotonic() + timeout
        delay = poll_interval
        current = self.status()
        while not current.is_forward_terminal:
            if cancel is not None and cancel.is_set():
                return WaitResult(outcome=WaitOutcome.CANCELLED, operation=current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return WaitResult(outcome=WaitOutcome.TIMED_OUT, operation=current)
            time.sleep(min(delay, remaining))
            current = self.status()
            delay = min(delay * 1.5, 5.0)
        return WaitResult(outcome=WaitOutcome.COMPLETED, operation=current)


class StatebackClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not token:
            raise ValueError("token must be non-empty")
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> StatebackClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def submit(
        self,
        *,
        effect: dict[str, str],
        arguments: object,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
        deployment_environment: str = "production",
        correlation_id: str | None = None,
    ) -> OperationHandle:
        headers = {"Idempotency-Key": idempotency_key}
        if correlation_id is not None:
            headers["X-Correlation-ID"] = correlation_id
        payload = self._request(
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
        operation = self._operation_status(payload)
        return OperationHandle(self, operation.operation_id)

    def get_operation(self, operation_id: str) -> OperationStatus:
        return self._operation_status(
            self._request("GET", f"/v1/operations/{operation_id}")
        )

    def get_audit(
        self, operation_id: str, *, after_sequence: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        payload = self._request(
            "GET",
            f"/v1/operations/{operation_id}/audit",
            params={"after_sequence": after_sequence, "limit": limit},
        )
        if not isinstance(payload, dict) or payload.get("contract_version") != "v1":
            raise StatebackTransportError("malformed_response")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> object:
        try:
            response = self._http.request(
                method, path, headers=headers, json=json, params=params
            )
        except httpx.HTTPError as exc:
            raise StatebackTransportError("transport_failed") from exc
        if response.is_success:
            try:
                return response.json()
            except ValueError as exc:
                raise StatebackTransportError("malformed_response") from exc
        try:
            body = response.json()
            error = body["error"]
            code = error["code"]
            retryable = error["retryable"]
            if not isinstance(code, str) or not isinstance(retryable, bool):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise StatebackTransportError("malformed_error_response") from exc
        raise StatebackClientError(
            code, status_code=response.status_code, retryable=retryable
        )

    @staticmethod
    def _operation_status(payload: object) -> OperationStatus:
        try:
            return OperationStatus.from_wire(payload)
        except ValueError as exc:
            raise StatebackTransportError("malformed_response") from exc
