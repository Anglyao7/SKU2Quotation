"""Add tenant-scoped on-demand catalog translation memory.

Revision ID: 20260729_0041
Revises: 20260729_0040
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260729_0041"
down_revision = "20260729_0040"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def _enable_tenant_rls(table_name: str, policy_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" '
        f"FOR ALL USING (tenant_id = {tenant}) "
        f"WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    op.create_table(
        "catalog_text_translations",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("source_locale", sa.String(20), nullable=False),
        sa.Column("target_locale", sa.String(20), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("provider_version", sa.String(120), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_locale <> target_locale",
            name="ck_catalog_text_translations_source_target_locale_different",
        ),
        sa.CheckConstraint(
            "length(source_hash) = 64",
            name="ck_catalog_text_translations_source_hash_sha256_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_text_translations_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_text_translations"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_locale",
            "target_locale",
            "provider",
            "provider_version",
            "source_hash",
            name="uq_catalog_text_translations_memory_key",
        ),
    )
    op.create_index(
        "ix_catalog_text_translations_tenant_accessed",
        "catalog_text_translations",
        ["tenant_id", "last_accessed_at"],
    )
    _enable_tenant_rls(
        "catalog_text_translations",
        "catalog_text_translations_tenant_isolation",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_text_translations_tenant_accessed",
        table_name="catalog_text_translations",
    )
    op.drop_table("catalog_text_translations")
