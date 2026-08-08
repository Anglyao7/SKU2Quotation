"""Add resumable pause checkpoints to catalog translation jobs.

Revision ID: 20260808_0056
Revises: 20260808_0055
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260808_0056"
down_revision = "20260808_0055"
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
        "uq_catalog_translation_jobs_active_tenant_locale",
        "catalog_translation_jobs",
        ["tenant_id", "target_locale"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )


def upgrade() -> None:
    op.drop_index(
        "uq_catalog_translation_jobs_active_tenant_locale",
        table_name="catalog_translation_jobs",
    )
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.drop_constraint(
            "ck_catalog_translation_jobs_status_allowed",
            type_="check",
        )
        batch.drop_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            type_="check",
        )
        batch.add_column(
            sa.Column(
                "remaining_sku_ids",
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
            "ck_catalog_translation_jobs_status_allowed",
            "status IN ('QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'FAILED')",
        )
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            "stage IN ('QUEUED', 'PREPARING', 'TRANSLATING', 'PACKAGING', "
            "'UPLOADING', 'PAUSED', 'PUBLISHED', 'FAILED')",
        )
    _create_active_job_index(include_paused=True)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE catalog_translation_jobs SET status = 'FAILED', stage = 'FAILED', "
            "error_message = COALESCE(error_message, 'Paused during migration downgrade'), "
            "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP) "
            "WHERE status = 'PAUSED'"
        )
    )
    op.drop_index(
        "uq_catalog_translation_jobs_active_tenant_locale",
        table_name="catalog_translation_jobs",
    )
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.drop_constraint(
            "ck_catalog_translation_jobs_status_allowed",
            type_="check",
        )
        batch.drop_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            type_="check",
        )
        batch.drop_column("paused_at")
        batch.drop_column("pause_requested_at")
        batch.drop_column("remaining_sku_ids")
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_status_allowed",
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
        )
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            "stage IN ('QUEUED', 'PREPARING', 'TRANSLATING', 'PACKAGING', "
            "'UPLOADING', 'PUBLISHED', 'FAILED')",
        )
    _create_active_job_index(include_paused=False)
