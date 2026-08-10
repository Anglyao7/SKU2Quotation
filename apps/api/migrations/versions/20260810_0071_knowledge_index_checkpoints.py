"""Add resumable pause checkpoints to product knowledge indexing.

Revision ID: 20260810_0071
Revises: 20260810_0070
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260810_0071"
down_revision = "20260810_0070"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _create_active_job_index(*, include_paused: bool) -> None:
    states = "'QUEUED', 'RUNNING', 'PAUSED'" if include_paused else "'QUEUED', 'RUNNING'"
    predicate = sa.text(f"status IN ({states}) AND deleted_at IS NULL")
    op.create_index(
        "uq_knowledge_index_jobs_active_tenant",
        "knowledge_index_jobs",
        ["tenant_id"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def upgrade() -> None:
    op.drop_index(
        "uq_knowledge_index_jobs_active_tenant",
        table_name="knowledge_index_jobs",
    )
    with op.batch_alter_table("knowledge_index_jobs") as batch:
        batch.drop_constraint(
            "ck_knowledge_index_jobs_status_allowed",
            type_="check",
        )
        batch.add_column(
            sa.Column(
                "remaining_product_ids",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_knowledge_index_jobs_status_allowed",
            "status IN ('QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'FAILED')",
        )
    _create_active_job_index(include_paused=True)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE knowledge_index_jobs SET status = 'FAILED', "
            "error_message = COALESCE(error_message, 'Paused during migration downgrade'), "
            "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) "
            "WHERE status = 'PAUSED'"
        )
    )
    op.drop_index(
        "uq_knowledge_index_jobs_active_tenant",
        table_name="knowledge_index_jobs",
    )
    with op.batch_alter_table("knowledge_index_jobs") as batch:
        batch.drop_constraint(
            "ck_knowledge_index_jobs_status_allowed",
            type_="check",
        )
        batch.drop_column("paused_at")
        batch.drop_column("pause_requested_at")
        batch.drop_column("remaining_product_ids")
        batch.create_check_constraint(
            "ck_knowledge_index_jobs_status_allowed",
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
        )
    _create_active_job_index(include_paused=False)
