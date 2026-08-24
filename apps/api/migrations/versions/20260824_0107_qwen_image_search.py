"""Add managed Qwen image search and resumable image indexing.

Revision ID: 20260824_0107
Revises: 20260823_0106
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260824_0107"
down_revision = "20260823_0106"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _audit() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    with op.batch_alter_table("image_embeddings") as batch:
        batch.drop_constraint(
            "ck_image_embeddings_dimensions_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_image_embeddings_dimensions_supported",
            "dimensions IN (256, 384, 512, 768, 1024, 1536, 2048, 2560)",
        )
    with op.batch_alter_table("image_searches") as batch:
        batch.drop_constraint(
            "ck_image_searches_dimensions_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_image_searches_dimensions_supported",
            "dimensions IN (256, 384, 512, 768, 1024, 1536, 2048, 2560)",
        )

    op.create_table(
        "image_embedding_provider_settings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "provider",
            sa.String(40),
            nullable=False,
            server_default="dashscope",
        ),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "max_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", _uuid(), nullable=True),
        *_audit(),
        sa.CheckConstraint(
            "provider = 'dashscope'",
            name="ck_image_embedding_provider_settings_provider_supported",
        ),
        sa.CheckConstraint(
            "dimensions IN (256, 512, 768, 1024, 1536, 2048, 2560)",
            name="ck_image_embedding_provider_settings_dimensions_supported",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="ck_image_embedding_provider_settings_timeout_supported",
        ),
        sa.CheckConstraint(
            "max_retry_count >= 0 AND max_retry_count <= 5",
            name="ck_image_embedding_provider_settings_max_retry_count_supported",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_image_embedding_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_image_embedding_provider_settings_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
    )

    op.create_table(
        "image_index_jobs",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("requested_by_membership_id", _uuid(), nullable=False),
        sa.Column("requested_by_user_id", _uuid(), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("total_images", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_images", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_images", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embeddings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_image_id", _uuid(), nullable=True),
        sa.Column("current_product_name", sa.String(500), nullable=True),
        sa.Column("model_provider", sa.String(60), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("remaining_image_ids", JSON_DOCUMENT, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit(),
        sa.CheckConstraint(
            "mode IN ('INCREMENTAL', 'FULL_REBUILD')",
            name="ck_image_index_jobs_mode_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'PAUSED', 'SUCCEEDED', 'FAILED')",
            name="ck_image_index_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "total_images >= 0",
            name="ck_image_index_jobs_total_images_nonnegative",
        ),
        sa.CheckConstraint(
            "processed_images >= 0 AND processed_images <= total_images",
            name="ck_image_index_jobs_processed_images_valid",
        ),
        sa.CheckConstraint(
            "failed_images >= 0",
            name="ck_image_index_jobs_failed_images_nonnegative",
        ),
        sa.CheckConstraint(
            "embeddings >= 0",
            name="ck_image_index_jobs_embeddings_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_image_index_jobs_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_image_index_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_image_index_jobs_requested_by_user",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_image_index_jobs_tenant_identity",
        ),
    )
    op.create_index(
        "ix_image_index_jobs_tenant_created",
        "image_index_jobs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_image_index_jobs_active_tenant",
        "image_index_jobs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING', 'PAUSED') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status IN ('QUEUED', 'RUNNING', 'PAUSED') AND deleted_at IS NULL"
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_image_embeddings_hnsw_1024 "
            "ON image_embeddings USING hnsw "
            "((embedding::vector(1024)) vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64) "
            "WHERE status='ACTIVE' AND deleted_at IS NULL AND dimensions=1024"
        )
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "image_index_jobs" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "image_index_jobs" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "image_index_jobs_tenant_isolation" '
            'ON "image_index_jobs" '
            f"FOR ALL USING (tenant_id = {tenant}) "
            f"WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_image_embeddings_hnsw_1024")
    op.drop_index(
        "uq_image_index_jobs_active_tenant",
        table_name="image_index_jobs",
    )
    op.drop_index(
        "ix_image_index_jobs_tenant_created",
        table_name="image_index_jobs",
    )
    op.drop_table("image_index_jobs")
    op.drop_table("image_embedding_provider_settings")
    # The previous schema only accepts 384-dimensional vectors. A downgrade is
    # explicitly lossy for projections produced by managed Qwen dimensions.
    op.execute(
        "DELETE FROM vision_observations "
        "WHERE EXISTS ("
        "SELECT 1 FROM image_embeddings e "
        "WHERE e.tenant_id = vision_observations.tenant_id "
        "AND e.product_image_id = vision_observations.product_image_id "
        "AND e.model_provider = vision_observations.model_provider "
        "AND e.model_name = vision_observations.model_name "
        "AND e.model_version = vision_observations.model_version "
        "AND e.content_hash = vision_observations.content_hash "
        "AND e.dimensions <> 384"
        ")"
    )
    op.execute("DELETE FROM image_searches WHERE dimensions <> 384")
    op.execute("DELETE FROM image_embeddings WHERE dimensions <> 384")
    with op.batch_alter_table("image_searches") as batch:
        batch.drop_constraint(
            "ck_image_searches_dimensions_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_image_searches_dimensions_supported",
            "dimensions = 384",
        )
    with op.batch_alter_table("image_embeddings") as batch:
        batch.drop_constraint(
            "ck_image_embeddings_dimensions_supported",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_image_embeddings_dimensions_supported",
            "dimensions = 384",
        )
