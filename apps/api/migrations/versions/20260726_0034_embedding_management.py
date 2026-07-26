"""Add managed embedding settings and observable index jobs.

Revision ID: 20260726_0034
Revises: 20260726_0033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0034"
down_revision = "20260726_0033"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "embedding_provider_settings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column(
            "provider",
            sa.String(40),
            nullable=False,
            server_default="openai-compatible",
        ),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", U(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = 'openai-compatible'",
            name="ck_embedding_provider_settings_provider_supported",
        ),
        sa.CheckConstraint(
            "dimensions >= 1 AND dimensions <= 2000",
            name="ck_embedding_provider_settings_dimensions_supported",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="ck_embedding_provider_settings_timeout_supported",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_embedding_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_embedding_provider_settings_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_provider_settings"),
    )

    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("requested_by_membership_id", U(), nullable=False),
        sa.Column("requested_by_user_id", U(), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("total_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embeddings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_product_id", U(), nullable=True),
        sa.Column("current_product_name", sa.String(500), nullable=True),
        sa.Column("model_provider", sa.String(60), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('INCREMENTAL', 'FULL_REBUILD')",
            name="ck_knowledge_index_jobs_mode_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_knowledge_index_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "total_products >= 0",
            name="ck_knowledge_index_jobs_total_products_nonnegative",
        ),
        sa.CheckConstraint(
            "processed_products >= 0 AND processed_products <= total_products",
            name="ck_knowledge_index_jobs_processed_products_valid",
        ),
        sa.CheckConstraint(
            "failed_products >= 0",
            name="ck_knowledge_index_jobs_failed_products_nonnegative",
        ),
        sa.CheckConstraint(
            "embeddings >= 0",
            name="ck_knowledge_index_jobs_embeddings_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_knowledge_index_jobs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_knowledge_index_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_knowledge_index_jobs_requested_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_index_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_knowledge_index_jobs_tenant_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_index_jobs_tenant_created",
        "knowledge_index_jobs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_knowledge_index_jobs_active_tenant",
        "knowledge_index_jobs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "knowledge_index_jobs" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "knowledge_index_jobs" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "knowledge_index_jobs_tenant_isolation" '
            'ON "knowledge_index_jobs" '
            f"FOR ALL USING (tenant_id = {tenant}) "
            f"WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index(
        "uq_knowledge_index_jobs_active_tenant",
        table_name="knowledge_index_jobs",
    )
    op.drop_index(
        "ix_knowledge_index_jobs_tenant_created",
        table_name="knowledge_index_jobs",
    )
    op.drop_table("knowledge_index_jobs")
    op.drop_table("embedding_provider_settings")
