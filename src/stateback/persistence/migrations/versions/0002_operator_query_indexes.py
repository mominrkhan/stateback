"""Add indexes for bounded operator queries.

Revision ID: 0002_operator_query_indexes
Revises: 0001_journal_v1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_operator_query_indexes"
down_revision: str | None = "0001_journal_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_operations_created_at_operation_id",
        "operations",
        [sa.text("created_at DESC"), "operation_id"],
    )
    op.create_index(
        "ix_operations_state_created_at_operation_id",
        "operations",
        ["state", sa.text("created_at DESC"), "operation_id"],
    )
    op.create_index(
        "ix_operations_provider_created_at_operation_id",
        "operations",
        [
            sa.text("(intent -> 'effect' ->> 'provider')"),
            sa.text("created_at DESC"),
            "operation_id",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_operations_provider_created_at_operation_id", "operations")
    op.drop_index("ix_operations_state_created_at_operation_id", "operations")
    op.drop_index("ix_operations_created_at_operation_id", "operations")
