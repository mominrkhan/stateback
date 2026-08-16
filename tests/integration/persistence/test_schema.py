from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from tests.integration.persistence.conftest import JOURNAL_TABLES

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

CONSTRAINT_NAMES = (
    "pk_operations",
    "ck_operations_contract_version",
    "ck_operations_state",
    "ck_operations_version",
    "ck_operations_intent_digest",
    "ck_operations_risk_level",
    "uq_operations_idempotency_identity",
    "fk_operations_current_policy_decision_id_policy_decisions",
    "fk_operations_current_approval_id_approvals",
    "fk_operations_latest_attempt_id_execution_attempts",
    "fk_operations_latest_verification_id_verifications",
    "fk_operations_compensation_id_compensations",
    "ck_operations_timestamps",
    "uq_execution_attempts_operation_id_attempt_number",
    "ck_execution_attempts_lifecycle",
    "ck_execution_attempts_outcome",
    "ck_approvals_lifecycle",
    "ck_verifications_result",
    "ck_compensations_kind",
    "uq_compensations_idempotency_identity",
    "ck_compensations_arguments",
    "uq_compensation_attempts_compensation_id_attempt_number",
    "uq_audit_events_operation_id_sequence",
    "ck_audit_events_transition",
    "ck_outbox_events_aggregate_type",
    "ck_outbox_events_lifecycle",
)


def test_expected_tables(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).fetchall()
    names = [str(row[0]) for row in rows]
    assert names == [
        "alembic_version",
        "approvals",
        "audit_events",
        "compensation_attempts",
        "compensations",
        "execution_attempts",
        "operations",
        "outbox_events",
        "policy_decisions",
        "reconciliation_decisions",
        "verifications",
    ]
    assert set(JOURNAL_TABLES) <= set(names)


@pytest.mark.parametrize("constraint_name", CONSTRAINT_NAMES)
def test_constraint_names(engine: Engine, constraint_name: str) -> None:
    with engine.connect() as connection:
        found = connection.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
            {"name": constraint_name},
        ).scalar()
    assert found == 1


def test_append_only_triggers(engine: Engine) -> None:
    with engine.connect() as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            )
        }
    assert "trg_audit_events_append_only" in names
    assert "trg_policy_decisions_immutable" in names


def test_no_postgres_enum_types(engine: Engine) -> None:
    with engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public' AND t.typtype = 'e'
                """
            )
        ).scalar()
    assert count == 0


def test_partial_outbox_index(engine: Engine) -> None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT (indpred IS NOT NULL) AS is_partial
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                WHERE c.relname = 'ix_outbox_events_pending'
                """
            )
        ).fetchone()
    assert row is not None
    assert bool(row[0]) is True


def test_uq_operations_idempotency_identity_exists(engine: Engine) -> None:
    with engine.connect() as connection:
        found = connection.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conname = "
                "'uq_operations_idempotency_identity'"
            )
        ).scalar()
    assert found == 1
