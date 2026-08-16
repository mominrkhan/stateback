"""Pure executable domain model.

This package has no database, network, or provider I/O. Importing it MUST NOT
open sockets or connect to PostgreSQL.
"""

from __future__ import annotations

from stateback.domain.approval_binding import (
    ApprovalBindingDecision,
    evaluate_approval_binding,
)
from stateback.domain.attempt import ExecutionAttempt
from stateback.domain.audit import AuditEvent
from stateback.domain.canonical import canonical_json_bytes, sha256_hex
from stateback.domain.capability import (
    CompensationEvidence,
    CompensationRequest,
    EffectDescriptor,
    ExecutionEvidence,
    ProviderExecutionContext,
    ProviderExecutionRequest,
    ProviderKeySemantics,
    VerificationEvidence,
)
from stateback.domain.compensation import (
    PARENT_FOR_COMPENSATION_STATE,
    Compensation,
    CompensationAttempt,
)
from stateback.domain.crash import CrashDecision, interpret_execution_crash
from stateback.domain.enums import (
    ABSOLUTE_TERMINAL_STATES,
    CONTRACT_VERSION,
    FORWARD_TERMINAL_STATES,
    INITIAL_ATTEMPT_NUMBER,
    INITIAL_AUDIT_SEQUENCE,
    INITIAL_COMPENSATION_VERSION,
    INITIAL_OPERATION_VERSION,
    ApprovalBindingVerdict,
    ApprovalState,
    ArgumentsMode,
    AttemptState,
    AuditEventType,
    CompensationKind,
    CompensationState,
    CrashInterpretation,
    EffectOutcome,
    ErrorKind,
    EvidenceSource,
    IdempotencyMode,
    Mutability,
    OperationState,
    OutboxState,
    PolicyVerdict,
    PrincipalType,
    ReconciliationAction,
    RetrySafetyBasis,
    RetrySafetyVerdict,
    RiskLevel,
    TransitionVerdict,
    VerificationMode,
    VerificationState,
    VerificationTarget,
    WorkCommand,
)
from stateback.domain.errors import NormalizedError
from stateback.domain.evidence import ProviderEvidence
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import (
    IntentEnvelope,
    compensation_idempotency_identity,
    compute_canonical_arguments_hash,
    compute_intent_digest,
    operation_idempotency_identity,
)
from stateback.domain.jsonutil import JsonArray, JsonObject, json_from_plain
from stateback.domain.messaging import OutboxEvent, WorkMessageV1
from stateback.domain.operation import Operation, next_version
from stateback.domain.policy import Approval, PolicyDecision, PolicyObligations
from stateback.domain.reconciliation import ReconciliationDecision, ReconciliationInput
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.domain.retry_safety import (
    RetrySafetyDecision,
    evaluate_effect_retry_safety,
)
from stateback.domain.time import UtcTimestamp
from stateback.domain.transitions import (
    LEGAL_OPERATION_TRANSITIONS,
    TransitionDecision,
    compensation_parent_is_consistent,
    evaluate_approval_transition,
    evaluate_compensation_transition,
    evaluate_operation_transition,
    evaluate_outbox_transition,
)
from stateback.domain.verification import VerificationRequest, VerificationResult

__all__ = [
    "ABSOLUTE_TERMINAL_STATES",
    "CONTRACT_VERSION",
    "FORWARD_TERMINAL_STATES",
    "INITIAL_ATTEMPT_NUMBER",
    "INITIAL_AUDIT_SEQUENCE",
    "INITIAL_COMPENSATION_VERSION",
    "INITIAL_OPERATION_VERSION",
    "LEGAL_OPERATION_TRANSITIONS",
    "PARENT_FOR_COMPENSATION_STATE",
    "Approval",
    "ApprovalBindingDecision",
    "ApprovalBindingVerdict",
    "ApprovalState",
    "ArgumentsMode",
    "AttemptState",
    "AuditEvent",
    "AuditEventType",
    "Compensation",
    "CompensationAttempt",
    "CompensationEvidence",
    "CompensationKind",
    "CompensationRequest",
    "CompensationState",
    "ContractValidationError",
    "CrashDecision",
    "CrashInterpretation",
    "EffectDescriptor",
    "EffectOutcome",
    "EffectRef",
    "ErrorKind",
    "EvidenceSource",
    "ExecutionAttempt",
    "ExecutionEvidence",
    "IdempotencyMode",
    "IntentEnvelope",
    "JsonArray",
    "JsonObject",
    "Mutability",
    "NormalizedError",
    "OpaqueId",
    "Operation",
    "OperationState",
    "OutboxEvent",
    "OutboxState",
    "PolicyDecision",
    "PolicyObligations",
    "PolicyVerdict",
    "PrincipalRef",
    "PrincipalType",
    "ProviderEvidence",
    "ProviderExecutionContext",
    "ProviderExecutionRequest",
    "ProviderKeySemantics",
    "ReconciliationAction",
    "ReconciliationDecision",
    "ReconciliationInput",
    "RetrySafetyBasis",
    "RetrySafetyDecision",
    "RetrySafetyVerdict",
    "RiskLevel",
    "TransitionDecision",
    "TransitionVerdict",
    "UtcTimestamp",
    "VerificationEvidence",
    "VerificationMode",
    "VerificationRequest",
    "VerificationResult",
    "VerificationState",
    "VerificationTarget",
    "WorkCommand",
    "WorkMessageV1",
    "canonical_json_bytes",
    "compensation_idempotency_identity",
    "compensation_parent_is_consistent",
    "compute_canonical_arguments_hash",
    "compute_intent_digest",
    "evaluate_approval_binding",
    "evaluate_approval_transition",
    "evaluate_compensation_transition",
    "evaluate_effect_retry_safety",
    "evaluate_operation_transition",
    "evaluate_outbox_transition",
    "interpret_execution_crash",
    "json_from_plain",
    "next_version",
    "operation_idempotency_identity",
    "sha256_hex",
]
