from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.compensation import Compensation, CompensationAttempt
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.messaging import OutboxEvent
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval, PolicyDecision
from stateback.domain.reconciliation import ReconciliationDecision
from stateback.domain.verification import VerificationRequest, VerificationResult
from stateback.persistence.exceptions import MalformedRowError
from stateback.persistence.models import (
    ApprovalRow,
    AuditEventRow,
    CompensationAttemptRow,
    CompensationRow,
    ExecutionAttemptRow,
    OperationRow,
    OutboxEventRow,
    PolicyDecisionRow,
    ReconciliationDecisionRow,
    VerificationRow,
)
from stateback.persistence.types import (
    StoredReconciliationDecision,
    opaque_to_uuid,
    utc_from_db,
    uuid_to_opaque,
)


def _domain_from_wire[T](parser: Callable[[object], T], raw: object) -> T:
    try:
        return parser(raw)
    except ContractValidationError as exc:
        raise MalformedRowError(str(exc)) from exc


def _opt_uuid(opaque: OpaqueId | None) -> uuid.UUID | None:
    if opaque is None:
        return None
    return opaque_to_uuid(opaque)


def _opt_opaque(value: uuid.UUID | None) -> str | None:
    if value is None:
        return None
    return uuid_to_opaque(value).to_wire()


def _ts_wire(value: datetime) -> str:
    return utc_from_db(value).to_wire()


def _opt_ts_wire(value: datetime | None) -> str | None:
    if value is None:
        return None
    return utc_from_db(value).to_wire()


def operation_to_row(operation: Operation) -> OperationRow:
    return OperationRow(
        operation_id=opaque_to_uuid(operation.operation_id),
        contract_version=operation.contract_version,
        state=operation.state.value,
        version=operation.version,
        intent=operation.intent.to_wire(),
        intent_digest=operation.intent.intent_digest,
        risk_level=operation.risk_level.value,
        idempotency_identity=operation.idempotency_identity,
        current_policy_decision_id=_opt_uuid(operation.current_policy_decision_id),
        current_approval_id=_opt_uuid(operation.current_approval_id),
        latest_attempt_id=_opt_uuid(operation.latest_attempt_id),
        latest_verification_id=_opt_uuid(operation.latest_verification_id),
        compensation_id=_opt_uuid(operation.compensation_id),
        created_at=operation.created_at.value,
        updated_at=operation.updated_at.value,
    )


def operation_from_row(row: OperationRow) -> Operation:
    return _domain_from_wire(
        Operation.from_wire,
        {
            "contract_version": row.contract_version,
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "state": row.state,
            "version": row.version,
            "intent": row.intent,
            "risk_level": row.risk_level,
            "idempotency_identity": row.idempotency_identity,
            "current_policy_decision_id": _opt_opaque(row.current_policy_decision_id),
            "current_approval_id": _opt_opaque(row.current_approval_id),
            "latest_attempt_id": _opt_opaque(row.latest_attempt_id),
            "latest_verification_id": _opt_opaque(row.latest_verification_id),
            "compensation_id": _opt_opaque(row.compensation_id),
            "created_at": _ts_wire(row.created_at),
            "updated_at": _ts_wire(row.updated_at),
        },
    )


def attempt_to_row(attempt: ExecutionAttempt) -> ExecutionAttemptRow:
    return ExecutionAttemptRow(
        attempt_id=opaque_to_uuid(attempt.attempt_id),
        contract_version=attempt.contract_version,
        operation_id=opaque_to_uuid(attempt.operation_id),
        attempt_number=attempt.attempt_number,
        state=attempt.state.value,
        started_at=attempt.started_at.value,
        completed_at=None
        if attempt.completed_at is None
        else attempt.completed_at.value,
        provider_idempotency_key=attempt.provider_idempotency_key,
        external_operation_id=attempt.external_operation_id,
        external_resource_ids=list(attempt.external_resource_ids),
        outcome=None if attempt.outcome is None else attempt.outcome.value,
        evidence=None if attempt.evidence is None else attempt.evidence.to_wire(),
        error=None if attempt.error is None else attempt.error.to_wire(),
        correlation_id=attempt.correlation_id,
    )


def attempt_from_row(row: ExecutionAttemptRow) -> ExecutionAttempt:
    return _domain_from_wire(
        ExecutionAttempt.from_wire,
        {
            "contract_version": row.contract_version,
            "attempt_id": uuid_to_opaque(row.attempt_id).to_wire(),
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "attempt_number": row.attempt_number,
            "state": row.state,
            "started_at": _ts_wire(row.started_at),
            "completed_at": _opt_ts_wire(row.completed_at),
            "provider_idempotency_key": row.provider_idempotency_key,
            "external_operation_id": row.external_operation_id,
            "external_resource_ids": list(row.external_resource_ids),
            "outcome": row.outcome,
            "evidence": row.evidence,
            "error": row.error,
            "correlation_id": row.correlation_id,
        },
    )


def policy_to_row(decision: PolicyDecision) -> PolicyDecisionRow:
    obligations = decision.obligations
    return PolicyDecisionRow(
        policy_decision_id=opaque_to_uuid(decision.policy_decision_id),
        contract_version=decision.contract_version,
        operation_id=opaque_to_uuid(decision.operation_id),
        operation_version=decision.operation_version,
        intent_digest=decision.intent_digest,
        verdict=decision.verdict.value,
        reason_codes=list(decision.reason_codes),
        explanation=decision.explanation,
        require_verification=obligations.require_verification,
        max_automatic_execution_attempts=obligations.max_automatic_execution_attempts,
        max_automatic_recovery_attempts=obligations.max_automatic_recovery_attempts,
        automatic_compensation_allowed=obligations.automatic_compensation_allowed,
        operator_reason_required=obligations.operator_reason_required,
        approval_expires_at=(
            None
            if obligations.approval_expires_at is None
            else obligations.approval_expires_at.value
        ),
        policy_revision=decision.policy_revision,
        evaluated_at=decision.evaluated_at.value,
    )


def policy_from_row(row: PolicyDecisionRow) -> PolicyDecision:
    return _domain_from_wire(
        PolicyDecision.from_wire,
        {
            "contract_version": row.contract_version,
            "policy_decision_id": uuid_to_opaque(row.policy_decision_id).to_wire(),
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "operation_version": row.operation_version,
            "intent_digest": row.intent_digest,
            "verdict": row.verdict,
            "reason_codes": list(row.reason_codes),
            "explanation": row.explanation,
            "obligations": {
                "require_verification": row.require_verification,
                "max_automatic_execution_attempts": (
                    row.max_automatic_execution_attempts
                ),
                "max_automatic_recovery_attempts": (
                    row.max_automatic_recovery_attempts
                ),
                "automatic_compensation_allowed": row.automatic_compensation_allowed,
                "operator_reason_required": row.operator_reason_required,
                "approval_expires_at": _opt_ts_wire(row.approval_expires_at),
            },
            "policy_revision": row.policy_revision,
            "evaluated_at": _ts_wire(row.evaluated_at),
        },
    )


def approval_to_row(approval: Approval) -> ApprovalRow:
    return ApprovalRow(
        approval_id=opaque_to_uuid(approval.approval_id),
        contract_version=approval.contract_version,
        operation_id=opaque_to_uuid(approval.operation_id),
        operation_version=approval.operation_version,
        intent_digest=approval.intent_digest,
        policy_decision_id=opaque_to_uuid(approval.policy_decision_id),
        state=approval.state.value,
        requested_at=approval.requested_at.value,
        expires_at=None if approval.expires_at is None else approval.expires_at.value,
        decided_at=None if approval.decided_at is None else approval.decided_at.value,
        decided_by=None
        if approval.decided_by is None
        else approval.decided_by.to_wire(),
        reason=approval.reason,
    )


def approval_from_row(row: ApprovalRow) -> Approval:
    return _domain_from_wire(
        Approval.from_wire,
        {
            "contract_version": row.contract_version,
            "approval_id": uuid_to_opaque(row.approval_id).to_wire(),
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "operation_version": row.operation_version,
            "intent_digest": row.intent_digest,
            "policy_decision_id": uuid_to_opaque(row.policy_decision_id).to_wire(),
            "state": row.state,
            "requested_at": _ts_wire(row.requested_at),
            "expires_at": _opt_ts_wire(row.expires_at),
            "decided_at": _opt_ts_wire(row.decided_at),
            "decided_by": row.decided_by,
            "reason": row.reason,
        },
    )


def verification_to_row(
    request: VerificationRequest,
    result: VerificationResult | None,
) -> VerificationRow:
    return VerificationRow(
        verification_id=opaque_to_uuid(request.verification_id),
        contract_version=request.contract_version,
        operation_id=opaque_to_uuid(request.operation_id),
        operation_version=request.operation_version,
        target=request.target.value,
        target_attempt_id=_opt_uuid(request.target_attempt_id),
        effect_provider=request.effect.provider,
        effect_action=request.effect.action,
        effect_version=request.effect.version,
        external_operation_id=request.external_operation_id,
        external_resource_ids=list(request.external_resource_ids),
        idempotency_identity=request.idempotency_identity,
        provider_evidence_refs=[
            item.to_wire() for item in request.provider_evidence_refs
        ],
        requested_at=request.requested_at.value,
        result_outcome=None if result is None else result.outcome.value,
        result_evidence=None if result is None else result.evidence.to_wire(),
        result_error=(
            None if result is None or result.error is None else result.error.to_wire()
        ),
        result_completed_at=None if result is None else result.completed_at.value,
    )


def verification_from_row(
    row: VerificationRow,
) -> tuple[VerificationRequest, VerificationResult | None]:
    request = _domain_from_wire(
        VerificationRequest.from_wire,
        {
            "contract_version": row.contract_version,
            "verification_id": uuid_to_opaque(row.verification_id).to_wire(),
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "operation_version": row.operation_version,
            "target": row.target,
            "target_attempt_id": _opt_opaque(row.target_attempt_id),
            "effect": {
                "provider": row.effect_provider,
                "action": row.effect_action,
                "version": row.effect_version,
            },
            "external_operation_id": row.external_operation_id,
            "external_resource_ids": list(row.external_resource_ids),
            "idempotency_identity": row.idempotency_identity,
            "provider_evidence_refs": list(row.provider_evidence_refs),
            "requested_at": _ts_wire(row.requested_at),
        },
    )
    if row.result_completed_at is None:
        return request, None
    result = _domain_from_wire(
        VerificationResult.from_wire,
        {
            "contract_version": row.contract_version,
            "verification_id": uuid_to_opaque(row.verification_id).to_wire(),
            "outcome": row.result_outcome,
            "evidence": row.result_evidence,
            "error": row.result_error,
            "completed_at": _ts_wire(row.result_completed_at),
        },
    )
    return request, result


def compensation_to_row(compensation: Compensation) -> CompensationRow:
    wire = compensation.to_wire()
    arguments = wire["arguments"]
    return CompensationRow(
        compensation_id=opaque_to_uuid(compensation.compensation_id),
        contract_version=compensation.contract_version,
        original_operation_id=opaque_to_uuid(compensation.original_operation_id),
        kind=compensation.kind.value,
        state=compensation.state.value,
        version=compensation.version,
        intent_digest=compensation.intent_digest,
        arguments_mode=compensation.arguments_mode.value,
        arguments=arguments,
        arguments_ref=compensation.arguments_ref,
        idempotency_identity=compensation.idempotency_identity,
        requested_by=compensation.requested_by.to_wire(),
        policy_decision_id=_opt_uuid(compensation.policy_decision_id),
        created_at=compensation.created_at.value,
        updated_at=compensation.updated_at.value,
    )


def compensation_from_row(row: CompensationRow) -> Compensation:
    return _domain_from_wire(
        Compensation.from_wire,
        {
            "contract_version": row.contract_version,
            "compensation_id": uuid_to_opaque(row.compensation_id).to_wire(),
            "original_operation_id": uuid_to_opaque(
                row.original_operation_id
            ).to_wire(),
            "kind": row.kind,
            "state": row.state,
            "version": row.version,
            "intent_digest": row.intent_digest,
            "arguments_mode": row.arguments_mode,
            "arguments": row.arguments,
            "arguments_ref": row.arguments_ref,
            "idempotency_identity": row.idempotency_identity,
            "requested_by": row.requested_by,
            "policy_decision_id": _opt_opaque(row.policy_decision_id),
            "created_at": _ts_wire(row.created_at),
            "updated_at": _ts_wire(row.updated_at),
        },
    )


def compensation_attempt_to_row(
    attempt: CompensationAttempt,
) -> CompensationAttemptRow:
    return CompensationAttemptRow(
        compensation_attempt_id=opaque_to_uuid(attempt.compensation_attempt_id),
        contract_version=attempt.contract_version,
        compensation_id=opaque_to_uuid(attempt.compensation_id),
        attempt_number=attempt.attempt_number,
        state=attempt.state.value,
        started_at=attempt.started_at.value,
        completed_at=None
        if attempt.completed_at is None
        else attempt.completed_at.value,
        provider_idempotency_key=attempt.provider_idempotency_key,
        external_operation_id=attempt.external_operation_id,
        outcome=None if attempt.outcome is None else attempt.outcome.value,
        evidence=None if attempt.evidence is None else attempt.evidence.to_wire(),
        error=None if attempt.error is None else attempt.error.to_wire(),
    )


def compensation_attempt_from_row(row: CompensationAttemptRow) -> CompensationAttempt:
    return _domain_from_wire(
        CompensationAttempt.from_wire,
        {
            "contract_version": row.contract_version,
            "compensation_attempt_id": uuid_to_opaque(
                row.compensation_attempt_id
            ).to_wire(),
            "compensation_id": uuid_to_opaque(row.compensation_id).to_wire(),
            "attempt_number": row.attempt_number,
            "state": row.state,
            "started_at": _ts_wire(row.started_at),
            "completed_at": _opt_ts_wire(row.completed_at),
            "provider_idempotency_key": row.provider_idempotency_key,
            "external_operation_id": row.external_operation_id,
            "outcome": row.outcome,
            "evidence": row.evidence,
            "error": row.error,
        },
    )


def audit_to_row(event: AuditEvent) -> AuditEventRow:
    return AuditEventRow(
        audit_event_id=opaque_to_uuid(event.audit_event_id),
        contract_version=event.contract_version,
        operation_id=opaque_to_uuid(event.operation_id),
        sequence=event.sequence,
        event_type=event.event_type.value,
        from_state=None if event.from_state is None else event.from_state.value,
        to_state=None if event.to_state is None else event.to_state.value,
        operation_version=event.operation_version,
        actor=None if event.actor is None else event.actor.to_wire(),
        reason_code=event.reason_code,
        data=event.to_wire()["data"],
        correlation_id=event.correlation_id,
        created_at=event.created_at.value,
    )


def audit_from_row(row: AuditEventRow) -> AuditEvent:
    return _domain_from_wire(
        AuditEvent.from_wire,
        {
            "contract_version": row.contract_version,
            "audit_event_id": uuid_to_opaque(row.audit_event_id).to_wire(),
            "operation_id": uuid_to_opaque(row.operation_id).to_wire(),
            "sequence": row.sequence,
            "event_type": row.event_type,
            "from_state": row.from_state,
            "to_state": row.to_state,
            "operation_version": row.operation_version,
            "actor": row.actor,
            "reason_code": row.reason_code,
            "data": row.data,
            "correlation_id": row.correlation_id,
            "created_at": _ts_wire(row.created_at),
        },
    )


def outbox_to_row(event: OutboxEvent) -> OutboxEventRow:
    return OutboxEventRow(
        event_id=opaque_to_uuid(event.event_id),
        contract_version=event.contract_version,
        state=event.state.value,
        aggregate_type=event.aggregate_type,
        aggregate_id=opaque_to_uuid(event.aggregate_id),
        operation_version=event.operation_version,
        command=event.command.value,
        created_at=event.created_at.value,
        published_at=None if event.published_at is None else event.published_at.value,
        correlation_id=event.correlation_id,
    )


def outbox_from_row(row: OutboxEventRow) -> OutboxEvent:
    return _domain_from_wire(
        OutboxEvent.from_wire,
        {
            "contract_version": row.contract_version,
            "event_id": uuid_to_opaque(row.event_id).to_wire(),
            "state": row.state,
            "aggregate_type": row.aggregate_type,
            "aggregate_id": uuid_to_opaque(row.aggregate_id).to_wire(),
            "operation_version": row.operation_version,
            "command": row.command,
            "created_at": _ts_wire(row.created_at),
            "published_at": _opt_ts_wire(row.published_at),
            "correlation_id": row.correlation_id,
        },
    )


def reconciliation_to_row(
    stored: StoredReconciliationDecision,
) -> ReconciliationDecisionRow:
    return ReconciliationDecisionRow(
        reconciliation_decision_id=opaque_to_uuid(stored.reconciliation_decision_id),
        operation_id=opaque_to_uuid(stored.operation_id),
        operation_version=stored.operation_version,
        verification_id=_opt_uuid(stored.verification_id),
        action=stored.decision.action.value,
        reason_code=stored.decision.reason_code,
        created_at=stored.created_at.value,
    )


def reconciliation_from_row(
    row: ReconciliationDecisionRow,
) -> StoredReconciliationDecision:
    try:
        decision = ReconciliationDecision.from_wire(
            {"action": row.action, "reason_code": row.reason_code}
        )
        return StoredReconciliationDecision(
            reconciliation_decision_id=uuid_to_opaque(row.reconciliation_decision_id),
            operation_id=uuid_to_opaque(row.operation_id),
            operation_version=row.operation_version,
            verification_id=(
                None
                if row.verification_id is None
                else uuid_to_opaque(row.verification_id)
            ),
            decision=decision,
            created_at=utc_from_db(row.created_at),
        )
    except ContractValidationError as exc:
        raise MalformedRowError(str(exc)) from exc
