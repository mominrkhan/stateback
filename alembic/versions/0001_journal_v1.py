"""Phase 2 v1 durable journal.

Revision ID: 0001_journal_v1
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_journal_v1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPERATION_STATES = (
    "PENDING_POLICY",
    "AWAITING_APPROVAL",
    "READY",
    "EXECUTING",
    "VERIFYING",
    "UNKNOWN",
    "SUCCEEDED",
    "FAILED",
    "DENIED",
    "CANCELLED",
    "COMPENSATING",
    "COMPENSATION_UNKNOWN",
    "COMPENSATED",
    "COMPENSATION_FAILED",
    "MANUAL_INTERVENTION",
)
_ATTEMPT_STATES = ("STARTED", "COMPLETED")
_EFFECT_OUTCOMES = ("APPLIED", "NOT_APPLIED", "UNKNOWN")
_RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
_POLICY_VERDICTS = ("ALLOW", "DENY", "REQUIRE_APPROVAL")
_APPROVAL_STATES = ("PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED")
_COMPENSATION_KINDS = ("EXACT", "APPROXIMATE", "MITIGATING")
_COMPENSATION_STATES = (
    "PENDING",
    "EXECUTING",
    "VERIFYING",
    "UNKNOWN",
    "SUCCEEDED",
    "FAILED",
)
_VERIFICATION_TARGETS = ("ORIGINAL_EFFECT", "COMPENSATION")
_OUTBOX_STATES = ("PENDING", "PUBLISHED")
_WORK_COMMANDS = ("EXECUTE", "VERIFY", "COMPENSATE")
_ARGUMENTS_MODES = ("INLINE", "REFERENCE")
_RECONCILIATION_ACTIONS = (
    "MARK_SUCCEEDED",
    "MARK_FAILED",
    "MAKE_READY_FOR_SAFE_RETRY",
    "REMAIN_UNKNOWN",
    "REQUIRE_MANUAL_INTERVENTION",
)
_AUDIT_EVENT_TYPES = (
    "operation.created.v1",
    "policy.evaluated.v1",
    "approval.requested.v1",
    "approval.decided.v1",
    "operation.transitioned.v1",
    "execution.attempt_started.v1",
    "execution.evidence_recorded.v1",
    "verification.started.v1",
    "verification.completed.v1",
    "reconciliation.decided.v1",
    "compensation.requested.v1",
    "compensation.attempted.v1",
    "compensation.result.v1",
    "operator.action.v1",
    "outbox.diagnostic.v1",
    "manual_intervention.reason.v1",
    "security.control_decision.v1",
)


def _in_sql(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join("'" + value + "'" for value in values)
    return f"{column} IN ({quoted})"


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "operations",
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("intent", postgresql.JSONB(), nullable=False),
        sa.Column("intent_digest", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=False),
        sa.Column("idempotency_identity", sa.Text(), nullable=False),
        sa.Column("current_policy_decision_id", _uuid(), nullable=True),
        sa.Column("current_approval_id", _uuid(), nullable=True),
        sa.Column("latest_attempt_id", _uuid(), nullable=True),
        sa.Column("latest_verification_id", _uuid(), nullable=True),
        sa.Column("compensation_id", _uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("operation_id", name="pk_operations"),
        sa.UniqueConstraint(
            "idempotency_identity", name="uq_operations_idempotency_identity"
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint(_in_sql("state", _OPERATION_STATES), name="state"),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint(
            "(intent->>'intent_digest') = intent_digest",
            name="intent_digest",
        ),
        sa.CheckConstraint(_in_sql("risk_level", _RISK_LEVELS), name="risk_level"),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps"),
    )
    op.create_index("ix_operations_state", "operations", ["state"])
    op.create_index("ix_operations_intent_digest", "operations", ["intent_digest"])

    op.create_table(
        "execution_attempts",
        sa.Column("attempt_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_idempotency_key", sa.Text(), nullable=True),
        sa.Column("external_operation_id", sa.Text(), nullable=True),
        sa.Column("external_resource_ids", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_execution_attempts"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_execution_attempts_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "attempt_number",
            name="uq_execution_attempts_operation_id_attempt_number",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint("attempt_number >= 1", name="attempt_number"),
        sa.CheckConstraint(_in_sql("state", _ATTEMPT_STATES), name="state"),
        sa.CheckConstraint(
            "(state = 'STARTED' AND completed_at IS NULL AND outcome IS NULL) "
            "OR (state = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND outcome IS NOT NULL)",
            name="lifecycle",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR " + _in_sql("outcome", _EFFECT_OUTCOMES),
            name="outcome",
        ),
    )
    op.create_index(
        "ix_execution_attempts_operation_id", "execution_attempts", ["operation_id"]
    )

    op.create_table(
        "policy_decisions",
        sa.Column("policy_decision_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("intent_digest", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("require_verification", sa.Boolean(), nullable=False),
        sa.Column("max_automatic_execution_attempts", sa.Integer(), nullable=True),
        sa.Column("max_automatic_recovery_attempts", sa.Integer(), nullable=True),
        sa.Column("automatic_compensation_allowed", sa.Boolean(), nullable=False),
        sa.Column("operator_reason_required", sa.Boolean(), nullable=False),
        sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_revision", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("policy_decision_id", name="pk_policy_decisions"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_policy_decisions_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint("operation_version >= 1", name="operation_version"),
        sa.CheckConstraint(_in_sql("verdict", _POLICY_VERDICTS), name="verdict"),
    )
    op.create_index(
        "ix_policy_decisions_operation_id", "policy_decisions", ["operation_id"]
    )

    op.create_table(
        "approvals",
        sa.Column("approval_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("intent_digest", sa.Text(), nullable=False),
        sa.Column("policy_decision_id", _uuid(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("approval_id", name="pk_approvals"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_approvals_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.policy_decision_id"],
            name="fk_approvals_policy_decision_id_policy_decisions",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint("operation_version >= 1", name="operation_version"),
        sa.CheckConstraint(_in_sql("state", _APPROVAL_STATES), name="state"),
        sa.CheckConstraint(
            "(state = 'PENDING' AND decided_at IS NULL AND decided_by IS NULL) "
            "OR (state IN ('APPROVED','REJECTED','EXPIRED','CANCELLED') "
            "AND decided_at IS NOT NULL)",
            name="lifecycle",
        ),
    )
    op.create_index("ix_approvals_operation_id", "approvals", ["operation_id"])

    op.create_table(
        "verifications",
        sa.Column("verification_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("target_attempt_id", _uuid(), nullable=True),
        sa.Column("effect_provider", sa.Text(), nullable=False),
        sa.Column("effect_action", sa.Text(), nullable=False),
        sa.Column("effect_version", sa.Text(), nullable=False),
        sa.Column("external_operation_id", sa.Text(), nullable=True),
        sa.Column("external_resource_ids", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_identity", sa.Text(), nullable=False),
        sa.Column("provider_evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_outcome", sa.Text(), nullable=True),
        sa.Column("result_evidence", postgresql.JSONB(), nullable=True),
        sa.Column("result_error", postgresql.JSONB(), nullable=True),
        sa.Column("result_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("verification_id", name="pk_verifications"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_verifications_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint("operation_version >= 1", name="operation_version"),
        sa.CheckConstraint(_in_sql("target", _VERIFICATION_TARGETS), name="target"),
        sa.CheckConstraint(
            "(result_outcome IS NULL AND result_evidence IS NULL "
            "AND result_error IS NULL AND result_completed_at IS NULL) "
            "OR ("
            + _in_sql("result_outcome", _EFFECT_OUTCOMES)
            + " AND result_evidence IS NOT NULL "
            "AND result_completed_at IS NOT NULL)",
            name="result",
        ),
    )
    op.create_index("ix_verifications_operation_id", "verifications", ["operation_id"])

    op.create_table(
        "compensations",
        sa.Column("compensation_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("original_operation_id", _uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("intent_digest", sa.Text(), nullable=False),
        sa.Column("arguments_mode", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=True),
        sa.Column("arguments_ref", sa.Text(), nullable=True),
        sa.Column("idempotency_identity", sa.Text(), nullable=False),
        sa.Column("requested_by", postgresql.JSONB(), nullable=False),
        sa.Column("policy_decision_id", _uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("compensation_id", name="pk_compensations"),
        sa.ForeignKeyConstraint(
            ["original_operation_id"],
            ["operations.operation_id"],
            name="fk_compensations_original_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.policy_decision_id"],
            name="fk_compensations_policy_decision_id_policy_decisions",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "idempotency_identity", name="uq_compensations_idempotency_identity"
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint(
            "kind <> 'NONE' AND " + _in_sql("kind", _COMPENSATION_KINDS),
            name="kind",
        ),
        sa.CheckConstraint(_in_sql("state", _COMPENSATION_STATES), name="state"),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint(
            _in_sql("arguments_mode", _ARGUMENTS_MODES),
            name="arguments_mode",
        ),
        sa.CheckConstraint(
            "(arguments_mode = 'INLINE' AND arguments IS NOT NULL "
            "AND arguments_ref IS NULL) OR "
            "(arguments_mode = 'REFERENCE' AND arguments IS NULL "
            "AND arguments_ref IS NOT NULL)",
            name="arguments",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps"),
    )
    op.create_index(
        "ix_compensations_original_operation_id",
        "compensations",
        ["original_operation_id"],
    )

    op.create_table(
        "compensation_attempts",
        sa.Column("compensation_attempt_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("compensation_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_idempotency_key", sa.Text(), nullable=True),
        sa.Column("external_operation_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint(
            "compensation_attempt_id", name="pk_compensation_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["compensation_id"],
            ["compensations.compensation_id"],
            name="fk_compensation_attempts_compensation_id_compensations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "compensation_id",
            "attempt_number",
            name="uq_compensation_attempts_compensation_id_attempt_number",
        ),
        sa.CheckConstraint(
            "contract_version = 'v1'",
            name="contract_version",
        ),
        sa.CheckConstraint("attempt_number >= 1", name="attempt_number"),
        sa.CheckConstraint(_in_sql("state", _ATTEMPT_STATES), name="state"),
        sa.CheckConstraint(
            "(state = 'STARTED' AND completed_at IS NULL AND outcome IS NULL) "
            "OR (state = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND outcome IS NOT NULL)",
            name="lifecycle",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR " + _in_sql("outcome", _EFFECT_OUTCOMES),
            name="outcome",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("from_state", sa.Text(), nullable=True),
        sa.Column("to_state", sa.Text(), nullable=True),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("actor", postgresql.JSONB(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_event_id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_audit_events_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "sequence",
            name="uq_audit_events_operation_id_sequence",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint("sequence >= 1", name="sequence"),
        sa.CheckConstraint(
            _in_sql("event_type", _AUDIT_EVENT_TYPES), name="event_type"
        ),
        sa.CheckConstraint(
            "from_state IS NULL OR " + _in_sql("from_state", _OPERATION_STATES),
            name="from_state",
        ),
        sa.CheckConstraint(
            "to_state IS NULL OR " + _in_sql("to_state", _OPERATION_STATES),
            name="to_state",
        ),
        sa.CheckConstraint("operation_version >= 1", name="operation_version"),
        sa.CheckConstraint(
            "(event_type <> 'operation.transitioned.v1') "
            "OR (from_state IS NOT NULL AND to_state IS NOT NULL)",
            name="transition",
        ),
    )
    op.create_index("ix_audit_events_operation_id", "audit_events", ["operation_id"])

    op.create_table(
        "outbox_events",
        sa.Column("event_id", _uuid(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", _uuid(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["aggregate_id"],
            ["operations.operation_id"],
            name="fk_outbox_events_aggregate_id_operations",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("contract_version = 'v1'", name="contract_version"),
        sa.CheckConstraint(_in_sql("state", _OUTBOX_STATES), name="state"),
        sa.CheckConstraint("aggregate_type = 'operation'", name="aggregate_type"),
        sa.CheckConstraint("operation_version >= 1", name="operation_version"),
        sa.CheckConstraint(_in_sql("command", _WORK_COMMANDS), name="command"),
        sa.CheckConstraint(
            "(state = 'PENDING' AND published_at IS NULL) "
            "OR (state = 'PUBLISHED' AND published_at IS NOT NULL)",
            name="lifecycle",
        ),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["created_at", "event_id"],
        postgresql_where=sa.text("state = 'PENDING'"),
    )

    op.create_table(
        "reconciliation_decisions",
        sa.Column("reconciliation_decision_id", _uuid(), nullable=False),
        sa.Column("operation_id", _uuid(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("verification_id", _uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "reconciliation_decision_id", name="pk_reconciliation_decisions"
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["operations.operation_id"],
            name="fk_reconciliation_decisions_operation_id_operations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.verification_id"],
            name="fk_reconciliation_decisions_verification_id_verifications",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation_version >= 1",
            name="operation_version",
        ),
        sa.CheckConstraint(
            _in_sql("action", _RECONCILIATION_ACTIONS),
            name="action",
        ),
    )
    op.create_index(
        "ix_reconciliation_decisions_operation_id",
        "reconciliation_decisions",
        ["operation_id"],
    )

    op.create_foreign_key(
        "fk_operations_current_policy_decision_id_policy_decisions",
        "operations",
        "policy_decisions",
        ["current_policy_decision_id"],
        ["policy_decision_id"],
        source_schema=None,
        referent_schema=None,
        ondelete=None,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_operations_current_approval_id_approvals",
        "operations",
        "approvals",
        ["current_approval_id"],
        ["approval_id"],
        source_schema=None,
        referent_schema=None,
        ondelete=None,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_operations_latest_attempt_id_execution_attempts",
        "operations",
        "execution_attempts",
        ["latest_attempt_id"],
        ["attempt_id"],
        source_schema=None,
        referent_schema=None,
        ondelete=None,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_operations_latest_verification_id_verifications",
        "operations",
        "verifications",
        ["latest_verification_id"],
        ["verification_id"],
        source_schema=None,
        referent_schema=None,
        ondelete=None,
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_operations_compensation_id_compensations",
        "operations",
        "compensations",
        ["compensation_id"],
        ["compensation_id"],
        source_schema=None,
        referent_schema=None,
        ondelete=None,
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION stateback_forbid_row_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW
            EXECUTE FUNCTION stateback_forbid_row_mutation();
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_policy_decisions_immutable
            BEFORE UPDATE OR DELETE ON policy_decisions
            FOR EACH ROW
            EXECUTE FUNCTION stateback_forbid_row_mutation();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER trg_audit_events_append_only ON audit_events"))
    op.execute(
        sa.text("DROP TRIGGER trg_policy_decisions_immutable ON policy_decisions")
    )
    op.execute(sa.text("DROP FUNCTION stateback_forbid_row_mutation()"))
    op.drop_constraint(
        "fk_operations_compensation_id_compensations",
        "operations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_operations_latest_verification_id_verifications",
        "operations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_operations_latest_attempt_id_execution_attempts",
        "operations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_operations_current_approval_id_approvals",
        "operations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_operations_current_policy_decision_id_policy_decisions",
        "operations",
        type_="foreignkey",
    )
    op.drop_table("reconciliation_decisions")
    op.drop_table("outbox_events")
    op.drop_table("audit_events")
    op.drop_table("compensation_attempts")
    op.drop_table("compensations")
    op.drop_table("verifications")
    op.drop_table("approvals")
    op.drop_table("policy_decisions")
    op.drop_table("execution_attempts")
    op.drop_table("operations")
