"""Add managed reranking and a 1024-dimension product-vector index.

Revision ID: 20260822_0103
Revises: 20260820_0102
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260822_0103"
down_revision = "20260820_0102"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "rerank_provider_settings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column(
            "provider",
            sa.String(40),
            nullable=False,
            server_default="cohere-compatible",
        ),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("max_documents", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", U(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider = 'cohere-compatible'",
            name="ck_rerank_provider_settings_provider_supported",
        ),
        sa.CheckConstraint(
            "timeout_ms >= 100 AND timeout_ms <= 800",
            name="ck_rerank_provider_settings_timeout_ms_supported",
        ),
        sa.CheckConstraint(
            "max_documents >= 5 AND max_documents <= 30",
            name="ck_rerank_provider_settings_max_documents_supported",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_rerank_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_rerank_provider_settings_updated_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rerank_provider_settings"),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_embeddings_hnsw_1024 ON embeddings "
            "USING hnsw ((embedding::vector(1024)) vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 96) "
            "WHERE status = 'ACTIVE' AND deleted_at IS NULL "
            "AND dimensions = 1024"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw_1024")
    op.drop_table("rerank_provider_settings")
