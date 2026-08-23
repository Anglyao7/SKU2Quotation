"""Track concurrent catalog translation requests and their retries.

Revision ID: 20260823_0105
Revises: 20260823_0104
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260823_0105"
down_revision = "20260823_0104"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.add_column(
            sa.Column(
                "forced_sku_ids",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "catalog_concurrency",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch.create_check_constraint(
            "ck_translation_provider_settings_catalog_concurrency_supported",
            "catalog_concurrency >= 1 AND catalog_concurrency <= 10",
        )

    op.create_table(
        "catalog_translation_batches",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="QUEUED"),
        sa.Column("sku_ids", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sku_refs", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_byte_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"],
            ["catalog_translation_jobs.tenant_id", "catalog_translation_jobs.id"],
            name="fk_catalog_translation_batches_tenant_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_catalog_translation_batches_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "job_id",
            "sequence_no",
            name="uq_catalog_translation_batches_tenant_job_sequence",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_catalog_translation_batches_status_allowed",
        ),
        sa.CheckConstraint("sequence_no >= 1", name="ck_catalog_translation_batches_sequence_positive"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_catalog_translation_batches_attempt_count_nonnegative"),
        sa.CheckConstraint("total_skus >= 0", name="ck_catalog_translation_batches_total_skus_nonnegative"),
        sa.CheckConstraint("processed_skus >= 0", name="ck_catalog_translation_batches_processed_skus_nonnegative"),
        sa.CheckConstraint("failed_skus >= 0", name="ck_catalog_translation_batches_failed_skus_nonnegative"),
    )
    op.create_index(
        "ix_catalog_translation_batches_tenant_job_sequence",
        "catalog_translation_batches",
        ["tenant_id", "job_id", "sequence_no"],
    )

    op.create_table(
        "catalog_translation_batch_attempts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("batch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="RUNNING"),
        sa.Column("sku_ids", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sku_refs", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_byte_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["catalog_translation_batches.tenant_id", "catalog_translation_batches.id"],
            name="fk_catalog_translation_batch_attempts_tenant_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_catalog_translation_batch_attempts_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "batch_id",
            "attempt_no",
            name="uq_catalog_translation_batch_attempts_tenant_batch_attempt",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_catalog_translation_batch_attempts_status_allowed",
        ),
        sa.CheckConstraint("attempt_no >= 1", name="ck_catalog_translation_batch_attempts_attempt_positive"),
        sa.CheckConstraint("processed_skus >= 0", name="ck_catalog_translation_batch_attempts_processed_skus_nonnegative"),
        sa.CheckConstraint("failed_skus >= 0", name="ck_catalog_translation_batch_attempts_failed_skus_nonnegative"),
    )
    op.create_index(
        "ix_catalog_translation_batch_attempts_tenant_batch_created",
        "catalog_translation_batch_attempts",
        ["tenant_id", "batch_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_translation_batch_attempts_tenant_batch_created",
        table_name="catalog_translation_batch_attempts",
    )
    op.drop_table("catalog_translation_batch_attempts")
    op.drop_index(
        "ix_catalog_translation_batches_tenant_job_sequence",
        table_name="catalog_translation_batches",
    )
    op.drop_table("catalog_translation_batches")
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(
            "ck_translation_provider_settings_catalog_concurrency_supported",
            type_="check",
        )
        batch.drop_column("catalog_concurrency")
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.drop_column("forced_sku_ids")
