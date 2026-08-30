"""One application boundary for API, SDK, MCP, and operator surfaces."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from stateback.application.auth import AuthenticatedIdentity, AuthorizationError, Role
from stateback.application.ids import (
    approval_ids,
    compensation_ids,
    recovery_ids,
    request_identity,
    submit_ids,
)
from stateback.application.input_validation import validate_metadata
from stateback.application.models import OperationSearch, SubmitOperationRequest
from stateback.approval.commands import ApprovalDecisionCommand
from stateback.approval.results import ApprovalDisposition
from stateback.approval.service import ApprovalService
from stateback.compensation.commands import OperatorCompensationCommand
from stateback.compensation.eligibility import evaluate_start_eligibility
from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.enums import ApprovalState, OperationState, VerificationMode
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval, PolicyDecision
from stateback.domain.refs import EffectRef
from stateback.domain.secrets import key_is_forbidden, value_is_forbidden
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.repositories import OperationQuery
from stateback.persistence.types import StoredReconciliationDecision
from stateback.persistence.uow import unit_of_work
from stateback.providers.exceptions import UnsupportedEffectError
from stateback.providers.registry import CapabilityRegistry
from stateback.recovery.commands import OperatorVerificationCommand
from stateback.recovery.results import RecoveryDisposition
from stateback.recovery.service import RecoveryService
from stateback.runtime.commands import SubmitCommand
from stateback.runtime.results import RuntimeDisposition
from stateback.runtime.service import SynchronousRuntime
from stateback.semantic.models import SemanticStatus, SemanticSummary, empty_summary
from stateback.semantic.service import AuditSummaryService


class ApplicationServiceError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditPage:
    events: tuple[AuditEvent, ...]
    next_after_sequence: int | None

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": "v1",
            "items": [event.to_wire() for event in self.events],
            "next_after_sequence": self.next_after_sequence,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationPage:
    operations: tuple[Operation, ...]
    next_cursor: str | None

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": "v1",
            "items": [operation.to_wire() for operation in self.operations],
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderOverview:
    provider: str
    configured: bool
    supported_effects: tuple[EffectRef, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "supported_effects": [
                effect.to_wire() for effect in self.supported_effects
            ],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatorOverview:
    total_operations: int
    attention: dict[str, int]
    active: dict[str, int]
    recent_operations: tuple[Operation, ...]
    providers: tuple[ProviderOverview, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": "v1",
            "total_operations": self.total_operations,
            "attention": self.attention,
            "active": self.active,
            "recent_operations": [
                operation.to_wire() for operation in self.recent_operations
            ],
            "providers": [provider.to_wire() for provider in self.providers],
        }


_ATTENTION_STATES = frozenset(
    {
        OperationState.AWAITING_APPROVAL,
        OperationState.UNKNOWN,
        OperationState.MANUAL_INTERVENTION,
        OperationState.COMPENSATION_UNKNOWN,
        OperationState.COMPENSATION_FAILED,
    }
)


def _reconciliation_wire(stored: StoredReconciliationDecision) -> dict[str, object]:
    return {
        "reconciliation_decision_id": stored.reconciliation_decision_id.to_wire(),
        "operation_id": stored.operation_id.to_wire(),
        "operation_version": stored.operation_version,
        "verification_id": (
            None if stored.verification_id is None else stored.verification_id.to_wire()
        ),
        "decision": stored.decision.to_wire(),
        "created_at": stored.created_at.to_wire(),
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationReconstruction:
    operation: Operation
    policy_decisions: tuple[PolicyDecision, ...]
    approvals: tuple[Approval, ...]
    attempts: tuple[ExecutionAttempt, ...]
    verifications: tuple[tuple[VerificationRequest, VerificationResult | None], ...]
    reconciliations: tuple[StoredReconciliationDecision, ...]
    compensation: object | None
    compensation_attempts: tuple[object, ...]
    audit: tuple[AuditEvent, ...]
    available_actions: tuple[str, ...]

    def to_wire(self) -> dict[str, object]:
        def wires(values: tuple[object, ...]) -> list[object]:
            return [value.to_wire() for value in values]  # type: ignore[attr-defined]

        return {
            "contract_version": "v1",
            "operation": self.operation.to_wire(),
            "policy_decisions": wires(self.policy_decisions),
            "approvals": wires(self.approvals),
            "attempts": wires(self.attempts),
            "verifications": [
                {
                    "request": request.to_wire(),
                    "result": None if result is None else result.to_wire(),
                }
                for request, result in self.verifications
            ],
            "reconciliations": [
                _reconciliation_wire(value) for value in self.reconciliations
            ],
            "compensation": (
                None if self.compensation is None else self.compensation.to_wire()  # type: ignore[attr-defined]
            ),
            "compensation_attempts": wires(self.compensation_attempts),
            "audit": [event.to_wire() for event in self.audit],
            "available_actions": list(self.available_actions),
        }


def _read_allowed(identity: AuthenticatedIdentity, operation: Operation) -> bool:
    if Role.OPERATOR in identity.roles:
        return True
    return (
        bool(identity.roles.intersection({Role.CALLER, Role.READER}))
        and operation.intent.requester.type is identity.principal.type
        and operation.intent.requester.id == identity.principal.id
    )


def _cursor(operation: Operation) -> str:
    raw = f"{operation.created_at.to_wire()}|{operation.operation_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, OpaqueId]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode()
        created_at, operation_id = decoded.split("|", 1)
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        parsed_operation_id = OpaqueId.from_wire(operation_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApplicationServiceError("invalid_cursor") from exc
    return parsed_created_at, parsed_operation_id


def _parse_utc(value: str, *, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApplicationServiceError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApplicationServiceError(code)
    return parsed


def _validate_action_key(value: str) -> None:
    if not value or len(value) > 200 or not value.isascii():
        raise ApplicationServiceError("invalid_idempotency_key")


def _validated_operator_text(value: str, *, code: str, limit: int) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > limit
        or not normalized.isascii()
        or key_is_forbidden(normalized)
        or value_is_forbidden(normalized)
    ):
        raise ApplicationServiceError(code)
    return normalized


class ApplicationService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        runtime: SynchronousRuntime,
        approvals: ApprovalService | None = None,
        recovery: RecoveryService | None = None,
        compensation: CompensationService | None = None,
        registry: CapabilityRegistry | None = None,
        semantic_summaries: AuditSummaryService | None = None,
        configured_providers: frozenset[str] = frozenset(),
    ) -> None:
        self._factory = session_factory
        self._runtime = runtime
        self._approvals = approvals
        self._recovery = recovery
        self._compensation = compensation
        self._registry = registry
        self._semantic_summaries = semantic_summaries
        self._configured_providers = configured_providers

    def _available_actions(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation: Operation,
        policy_decisions: tuple[PolicyDecision, ...],
        attempts: tuple[ExecutionAttempt, ...],
    ) -> tuple[str, ...]:
        actions: list[str] = []
        if (
            self._approvals is not None
            and Role.APPROVER in identity.roles
            and operation.state is OperationState.AWAITING_APPROVAL
            and operation.current_approval_id is not None
        ):
            actions.extend(("approve", "reject"))
        if self._registry is None:
            return tuple(actions)
        try:
            descriptor = self._registry.descriptor(operation.intent.effect)
        except UnsupportedEffectError:
            return tuple(actions)
        if (
            self._recovery is not None
            and operation.state is OperationState.MANUAL_INTERVENTION
            and descriptor.verification_mode is not VerificationMode.NONE
        ):
            actions.append("verify")
        if self._compensation is not None:
            if (
                operation.state
                in {
                    OperationState.SUCCEEDED,
                    OperationState.FAILED,
                    OperationState.MANUAL_INTERVENTION,
                }
                and policy_decisions
            ):
                policy = next(
                    (
                        candidate
                        for candidate in policy_decisions
                        if candidate.policy_decision_id
                        == operation.current_policy_decision_id
                    ),
                    None,
                )
                if policy is None:
                    return tuple(actions)
                latest_attempt = attempts[-1] if attempts else None
                decision = evaluate_start_eligibility(
                    operation=operation,
                    descriptor=descriptor,
                    obligations=policy.obligations,
                    latest_original_attempt=latest_attempt,
                    automatic=False,
                    operator=True,
                )
                if decision.allowed:
                    actions.append("compensate")
            if operation.state is OperationState.COMPENSATION_FAILED:
                actions.append("retry_compensation")
            if operation.state in {
                OperationState.COMPENSATING,
                OperationState.COMPENSATION_UNKNOWN,
                OperationState.COMPENSATION_FAILED,
            }:
                actions.append("escalate_compensation")
        return tuple(actions)

    def submit(
        self,
        *,
        identity: AuthenticatedIdentity,
        idempotency_key: str,
        request: SubmitOperationRequest,
        correlation_id: str | None = None,
    ) -> Operation:
        identity.require(Role.CALLER)
        if (
            not idempotency_key
            or len(idempotency_key) > 200
            or not idempotency_key.isascii()
        ):
            raise ApplicationServiceError("invalid_idempotency_key")
        validate_metadata(request.metadata)
        if correlation_id is not None:
            correlation_id = _validated_operator_text(
                correlation_id, code="invalid_correlation_id", limit=200
            )
        stable_identity = request_identity(identity.principal, idempotency_key)
        result = self._runtime.submit(
            SubmitCommand(
                effect=request.effect,
                arguments=request.arguments,
                requester=identity.principal,
                metadata=request.metadata,
                ids=submit_ids(stable_identity),
                correlation_id=correlation_id,
                deployment_environment=request.deployment_environment,
            )
        )
        if result.operation is not None:
            if result.reason_code == "intent_conflict":
                raise ApplicationServiceError("idempotency_conflict")
            return result.operation
        if result.disposition is RuntimeDisposition.INFRASTRUCTURE_FAILURE:
            raise ApplicationServiceError(result.reason_code, retryable=True)
        raise ApplicationServiceError(result.reason_code)

    def get_operation(
        self, identity: AuthenticatedIdentity, operation_id: OpaqueId
    ) -> Operation:
        identity.require(Role.CALLER, Role.READER, Role.OPERATOR)
        with unit_of_work(self._factory) as uow:
            operation = uow.operations.get(operation_id)
        if operation is None:
            raise ApplicationServiceError("not_found")
        if not _read_allowed(identity, operation):
            raise AuthorizationError("operation_read_forbidden")
        return operation

    def audit_page(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: OpaqueId,
        after_sequence: int = 0,
        limit: int = 50,
    ) -> AuditPage:
        if after_sequence < 0 or not 1 <= limit <= 100:
            raise ApplicationServiceError("invalid_pagination")
        self.get_operation(identity, operation_id)
        with unit_of_work(self._factory) as uow:
            events, has_more = uow.audit_events.page_for_operation(
                operation_id, after_sequence=after_sequence, limit=limit
            )
        next_value = events[-1].sequence if has_more else None
        return AuditPage(events=events, next_after_sequence=next_value)

    def search_operations(
        self, identity: AuthenticatedIdentity, query: OperationSearch
    ) -> OperationPage:
        identity.require(Role.OPERATOR)
        if query.attention and query.state is not None:
            raise ApplicationServiceError("invalid_filter_combination")
        states: frozenset[OperationState] | None = None
        if query.attention:
            states = _ATTENTION_STATES
        if query.state is not None:
            try:
                states = frozenset({OperationState(query.state)})
            except ValueError as exc:
                raise ApplicationServiceError("invalid_state") from exc
        lower = None
        if query.created_from is not None:
            lower = _parse_utc(query.created_from, code="invalid_created_from")
        upper = None
        if query.created_to is not None:
            upper = _parse_utc(query.created_to, code="invalid_created_to")
        cursor_created_at = None
        cursor_operation_id = None
        if query.cursor is not None:
            cursor_created_at, cursor_operation_id = _decode_cursor(query.cursor)
        with unit_of_work(self._factory) as uow:
            result = uow.operations.search(
                OperationQuery(
                    states=states,
                    provider=query.provider,
                    created_from=lower,
                    created_to=upper,
                    cursor_created_at=cursor_created_at,
                    cursor_operation_id=cursor_operation_id,
                    limit=query.limit,
                )
            )
        if not result.cursor_found:
            raise ApplicationServiceError("invalid_cursor")
        next_value = _cursor(result.operations[-1]) if result.has_more else None
        return OperationPage(operations=result.operations, next_cursor=next_value)

    def operator_overview(self, identity: AuthenticatedIdentity) -> OperatorOverview:
        identity.require(Role.OPERATOR)
        with unit_of_work(self._factory) as uow:
            persisted_counts = uow.operations.count_by_state()
            recent = uow.operations.search(OperationQuery(limit=8)).operations

        counts = {state: persisted_counts.get(state, 0) for state in OperationState}

        effects_by_provider: dict[str, list[EffectRef]] = {}
        if self._registry is not None:
            for effect in self._registry.listed_effects():
                effects_by_provider.setdefault(effect.provider, []).append(effect)
        providers = tuple(
            ProviderOverview(
                provider=provider,
                configured=provider in self._configured_providers,
                supported_effects=tuple(effects),
            )
            for provider, effects in effects_by_provider.items()
        )
        return OperatorOverview(
            total_operations=sum(counts.values()),
            attention={
                "awaiting_approval": counts[OperationState.AWAITING_APPROVAL],
                "unknown": counts[OperationState.UNKNOWN],
                "manual_intervention": counts[OperationState.MANUAL_INTERVENTION],
                "compensation_issues": (
                    counts[OperationState.COMPENSATION_UNKNOWN]
                    + counts[OperationState.COMPENSATION_FAILED]
                ),
            },
            active={
                "executing": counts[OperationState.EXECUTING],
                "verifying": counts[OperationState.VERIFYING],
                "compensating": counts[OperationState.COMPENSATING],
            },
            recent_operations=recent,
            providers=providers,
        )

    def reconstruct(
        self, identity: AuthenticatedIdentity, operation_id: OpaqueId
    ) -> OperationReconstruction:
        identity.require(Role.OPERATOR)
        with unit_of_work(self._factory) as uow:
            operation = uow.operations.get(operation_id)
            if operation is None:
                raise ApplicationServiceError("not_found")
            compensation = uow.compensations.get_by_original_operation(operation_id)
            compensation_attempts = (
                []
                if compensation is None
                else uow.compensation_attempts.list_for_compensation(
                    compensation.compensation_id
                )
            )
            policy_decisions = tuple(
                uow.policy_decisions.list_for_operation(operation_id)
            )
            attempts = tuple(uow.attempts.list_for_operation(operation_id))
            return OperationReconstruction(
                operation=operation,
                policy_decisions=policy_decisions,
                approvals=tuple(uow.approvals.list_for_operation(operation_id)),
                attempts=attempts,
                verifications=tuple(uow.verifications.list_for_operation(operation_id)),
                reconciliations=tuple(
                    uow.reconciliation_decisions.list_for_operation(operation_id)
                ),
                compensation=compensation,
                compensation_attempts=tuple(compensation_attempts),
                audit=tuple(uow.audit_events.list_for_operation(operation_id)),
                available_actions=self._available_actions(
                    identity=identity,
                    operation=operation,
                    policy_decisions=policy_decisions,
                    attempts=attempts,
                ),
            )

    def semantic_summary(
        self, identity: AuthenticatedIdentity, operation_id: OpaqueId
    ) -> SemanticSummary:
        reconstruction = self.reconstruct(identity, operation_id)
        if self._semantic_summaries is None:
            return empty_summary(
                status=SemanticStatus.UNAVAILABLE,
                reason_code="semantic_not_configured",
                operation=reconstruction.operation,
                audit=reconstruction.audit,
                provider=None,
                model=None,
            )
        return self._semantic_summaries.summarize(
            operation=reconstruction.operation,
            audit=reconstruction.audit,
        )

    def decide_approval(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: OpaqueId,
        approval_id: OpaqueId,
        expected_version: int,
        decision: ApprovalState,
        reason: str,
        action_key: str,
        correlation_id: str,
    ) -> Operation:
        identity.require(Role.APPROVER)
        _validate_action_key(action_key)
        reason = _validated_operator_text(reason, code="invalid_reason", limit=500)
        correlation_id = _validated_operator_text(
            correlation_id, code="invalid_correlation_id", limit=200
        )
        if self._approvals is None:
            raise ApplicationServiceError(
                "approval_service_unavailable", retryable=True
            )
        result = self._approvals.decide(
            ApprovalDecisionCommand(
                operation_id=operation_id,
                approval_id=approval_id,
                expected_version=expected_version,
                decision=decision,
                actor=identity.principal,
                reason=reason,
                correlation_id=correlation_id,
                ids=approval_ids(operation_id, action_key),
            )
        )
        if result.disposition is ApprovalDisposition.UNAUTHORIZED:
            raise AuthorizationError(result.reason_code)
        if (
            result.disposition is not ApprovalDisposition.ACCEPTED
            or result.operation is None
        ):
            raise ApplicationServiceError(result.reason_code)
        return result.operation

    def request_verification(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: OpaqueId,
        expected_version: int,
        reason_code: str,
        action_key: str,
        correlation_id: str,
    ) -> Operation:
        identity.require(Role.OPERATOR)
        _validate_action_key(action_key)
        reason_code = _validated_operator_text(
            reason_code, code="invalid_reason", limit=200
        )
        correlation_id = _validated_operator_text(
            correlation_id, code="invalid_correlation_id", limit=200
        )
        if self._recovery is None:
            raise ApplicationServiceError(
                "recovery_service_unavailable", retryable=True
            )
        result = self._recovery.start_operator_verification(
            OperatorVerificationCommand(
                operation_id=operation_id,
                expected_version=expected_version,
                ids=recovery_ids(operation_id, action_key),
                actor=identity.principal,
                reason_code=reason_code,
                correlation_id=correlation_id,
            )
        )
        if (
            result.disposition is not RecoveryDisposition.ACCEPTED
            or result.operation is None
        ):
            raise ApplicationServiceError(result.reason_code)
        return result.operation

    def compensate(
        self,
        *,
        identity: AuthenticatedIdentity,
        operation_id: OpaqueId,
        expected_version: int,
        action_key: str,
        reason_code: str,
        correlation_id: str,
        retry: bool = False,
        escalate: bool = False,
    ) -> Operation:
        identity.require(Role.OPERATOR)
        _validate_action_key(action_key)
        reason_code = _validated_operator_text(
            reason_code, code="invalid_reason", limit=200
        )
        correlation_id = _validated_operator_text(
            correlation_id, code="invalid_correlation_id", limit=200
        )
        if self._compensation is None:
            raise ApplicationServiceError(
                "compensation_service_unavailable", retryable=True
            )
        command = OperatorCompensationCommand(
            operation_id=operation_id,
            expected_version=expected_version,
            ids=compensation_ids(operation_id, action_key),
            actor=identity.principal,
            correlation_id=correlation_id,
            reason_code=reason_code,
        )
        if escalate:
            result = self._compensation.escalate(command)
        elif retry:
            result = self._compensation.retry_failed_compensation(command)
        else:
            result = self._compensation.start_operator_compensation(command)
        if (
            result.disposition
            not in {CompensationDisposition.ACCEPTED, CompensationDisposition.IN_FLIGHT}
            or result.operation is None
        ):
            raise ApplicationServiceError(result.reason_code)
        return result.operation
