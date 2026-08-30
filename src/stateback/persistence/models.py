from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql.naming import conv

from stateback.persistence.types import (
    APPROVAL_STATES,
    ARGUMENTS_MODES,
    ATTEMPT_STATES,
    AUDIT_EVENT_TYPES,
    COMPENSATION_KINDS,
    COMPENSATION_STATES,
    EFFECT_OUTCOMES,
    NAMING_CONVENTION,
    OPERATION_STATES,
    OUTBOX_STATES,
    POLICY_VERDICTS,
    RECONCILIATION_ACTIONS,
    RISK_LEVELS,
    VERIFICATION_TARGETS,
    WORK_COMMANDS,
)


def _in_sql(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class OperationRow(Base):
    __tablename__ = "operations"

    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    intent: Mapped[dict[str, Any]] = mapped_column(postgresql.JSONB, nullable=False)
    intent_digest: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_identity: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    current_policy_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "policy_decisions.policy_decision_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    current_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "approvals.approval_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    latest_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "execution_attempts.attempt_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    latest_verification_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "verifications.verification_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    compensation_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey(
            "compensations.compensation_id",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint(_in_sql("state", OPERATION_STATES), name="state"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "(intent->>'intent_digest') = intent_digest",
            name="intent_digest",
        ),
        CheckConstraint(_in_sql("risk_level", RISK_LEVELS), name="risk_level"),
        CheckConstraint("updated_at >= created_at", name="timestamps"),
    )


Index(
    "ix_operations_created_at_operation_id",
    OperationRow.created_at.desc(),
    OperationRow.operation_id,
)
Index(
    "ix_operations_state_created_at_operation_id",
    OperationRow.state,
    OperationRow.created_at.desc(),
    OperationRow.operation_id,
)
Index(
    "ix_operations_provider_created_at_operation_id",
    OperationRow.intent["effect"]["provider"].astext,
    OperationRow.created_at.desc(),
    OperationRow.operation_id,
)


class ExecutionAttemptRow(Base):
    __tablename__ = "execution_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_operation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_resource_ids: Mapped[list[str]] = mapped_column(
        postgresql.JSONB, nullable=False
    )
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("attempt_number >= 1", name="attempt_number"),
        CheckConstraint(_in_sql("state", ATTEMPT_STATES), name="state"),
        CheckConstraint(
            "(state = 'STARTED' AND completed_at IS NULL AND outcome IS NULL) "
            "OR (state = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND outcome IS NOT NULL)",
            name="lifecycle",
        ),
        CheckConstraint(
            "outcome IS NULL OR " + _in_sql("outcome", EFFECT_OUTCOMES),
            name="outcome",
        ),
        UniqueConstraint(
            "operation_id",
            "attempt_number",
            name=conv("uq_execution_attempts_operation_id_attempt_number"),
        ),
    )


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"

    policy_decision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    intent_digest: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(postgresql.JSONB, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    require_verification: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_automatic_execution_attempts: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    max_automatic_recovery_attempts: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    automatic_compensation_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )
    operator_reason_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    approval_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    policy_revision: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(_in_sql("verdict", POLICY_VERDICTS), name="verdict"),
    )


class ApprovalRow(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    intent_digest: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("policy_decisions.policy_decision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(_in_sql("state", APPROVAL_STATES), name="state"),
        CheckConstraint(
            "(state = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL) "
            "OR (state IN ('APPROVED','REJECTED','EXPIRED','CANCELLED') "
            "AND decided_at IS NOT NULL)",
            name="lifecycle",
        ),
    )


class VerificationRow(Base):
    __tablename__ = "verifications"

    verification_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    target_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=True
    )
    effect_provider: Mapped[str] = mapped_column(Text, nullable=False)
    effect_action: Mapped[str] = mapped_column(Text, nullable=False)
    effect_version: Mapped[str] = mapped_column(Text, nullable=False)
    external_operation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_resource_ids: Mapped[list[str]] = mapped_column(
        postgresql.JSONB, nullable=False
    )
    idempotency_identity: Mapped[str] = mapped_column(Text, nullable=False)
    provider_evidence_refs: Mapped[list[str]] = mapped_column(
        postgresql.JSONB, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    result_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    result_error: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    result_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(_in_sql("target", VERIFICATION_TARGETS), name="target"),
        CheckConstraint(
            "(result_outcome IS NULL AND result_evidence IS NULL "
            "AND result_error IS NULL AND result_completed_at IS NULL) "
            "OR ("
            + _in_sql("result_outcome", EFFECT_OUTCOMES)
            + " AND result_evidence IS NOT NULL "
            "AND result_completed_at IS NOT NULL)",
            name="result",
        ),
    )


class CompensationRow(Base):
    __tablename__ = "compensations"

    compensation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    original_operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    intent_digest: Mapped[str] = mapped_column(Text, nullable=False)
    arguments_mode: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[Any | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    arguments_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_identity: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    requested_by: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB, nullable=False
    )
    policy_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("policy_decisions.policy_decision_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint(
            "kind <> 'NONE' AND " + _in_sql("kind", COMPENSATION_KINDS),
            name="kind",
        ),
        CheckConstraint(_in_sql("state", COMPENSATION_STATES), name="state"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            _in_sql("arguments_mode", ARGUMENTS_MODES), name="arguments_mode"
        ),
        CheckConstraint(
            "(arguments_mode = 'INLINE' AND arguments IS NOT NULL "
            "AND arguments_ref IS NULL) OR "
            "(arguments_mode = 'REFERENCE' AND arguments IS NULL "
            "AND arguments_ref IS NOT NULL)",
            name="arguments",
        ),
        CheckConstraint("updated_at >= created_at", name="timestamps"),
    )


class CompensationAttemptRow(Base):
    __tablename__ = "compensation_attempts"

    compensation_attempt_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    compensation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("compensations.compensation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_operation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("attempt_number >= 1", name="attempt_number"),
        CheckConstraint(_in_sql("state", ATTEMPT_STATES), name="state"),
        CheckConstraint(
            "(state = 'STARTED' AND completed_at IS NULL AND outcome IS NULL) "
            "OR (state = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND outcome IS NOT NULL)",
            name="lifecycle",
        ),
        CheckConstraint(
            "outcome IS NULL OR " + _in_sql("outcome", EFFECT_OUTCOMES),
            name="outcome",
        ),
        UniqueConstraint(
            "compensation_id",
            "attempt_number",
            name=conv("uq_compensation_attempts_compensation_id_attempt_number"),
        ),
    )


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor: Mapped[dict[str, Any] | None] = mapped_column(
        postgresql.JSONB(none_as_null=True), nullable=True
    )
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Any] = mapped_column(postgresql.JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint(_in_sql("event_type", AUDIT_EVENT_TYPES), name="event_type"),
        CheckConstraint(
            "from_state IS NULL OR " + _in_sql("from_state", OPERATION_STATES),
            name="from_state",
        ),
        CheckConstraint(
            "to_state IS NULL OR " + _in_sql("to_state", OPERATION_STATES),
            name="to_state",
        ),
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(
            "(event_type <> 'operation.transitioned.v1') "
            "OR (from_state IS NOT NULL AND to_state IS NOT NULL)",
            name="transition",
        ),
        UniqueConstraint(
            "operation_id",
            "sequence",
            name=conv("uq_audit_events_operation_id_sequence"),
        ),
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("contract_version = 'v1'", name="contract_version"),
        CheckConstraint(_in_sql("state", OUTBOX_STATES), name="state"),
        CheckConstraint("aggregate_type = 'operation'", name="aggregate_type"),
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(_in_sql("command", WORK_COMMANDS), name="command"),
        CheckConstraint(
            "(state = 'PENDING' AND published_at IS NULL) "
            "OR (state = 'PUBLISHED' AND published_at IS NOT NULL)",
            name="lifecycle",
        ),
        Index(
            "ix_outbox_events_pending",
            "created_at",
            "event_id",
            postgresql_where=text("state = 'PENDING'"),
        ),
    )


class ReconciliationDecisionRow(Base):
    __tablename__ = "reconciliation_decisions"

    reconciliation_decision_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), primary_key=True
    )
    operation_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("operations.operation_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    verification_id: Mapped[uuid.UUID | None] = mapped_column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("verifications.verification_id", ondelete="RESTRICT"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("operation_version >= 1", name="operation_version"),
        CheckConstraint(_in_sql("action", RECONCILIATION_ACTIONS), name="action"),
    )
