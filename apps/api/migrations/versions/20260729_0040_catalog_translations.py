"""Add cached storefront translations and observable translation jobs.

Revision ID: 20260729_0040
Revises: 20260729_0039
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260729_0040"
down_revision = "20260729_0039"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


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
        "catalog_sku_translations",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("source_locale", sa.String(20), nullable=False),
        sa.Column("target_locale", sa.String(20), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_category", sa.String(300), nullable=True),
        sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(500), nullable=True),
        sa.Column(
            "tags",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("display_tag", sa.String(200), nullable=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("provider_version", sa.String(120), nullable=False),
        sa.Column("product_version", sa.Integer(), nullable=False),
        sa.Column("sku_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_locale <> target_locale",
            name="ck_catalog_sku_translations_source_target_locale_different",
        ),
        sa.CheckConstraint(
            "length(source_hash) = 64",
            name="ck_catalog_sku_translations_source_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "product_version >= 1",
            name="ck_catalog_sku_translations_product_version_positive",
        ),
        sa.CheckConstraint(
            "sku_version >= 1",
            name="ck_catalog_sku_translations_sku_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_sku_translations_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_catalog_sku_translations_tenant_sku",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_sku_translations"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_sku_translations_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sku_id",
            "target_locale",
            name="uq_catalog_sku_translations_tenant_sku_locale",
        ),
    )
    op.create_index(
        "ix_catalog_sku_translations_tenant_locale",
        "catalog_sku_translations",
        ["tenant_id", "target_locale"],
    )
    op.create_index(
        "ix_catalog_sku_translations_tenant_category_locale",
        "catalog_sku_translations",
        ["tenant_id", "source_category", "target_locale"],
    )

    op.create_table(
        "catalog_translation_jobs",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("requested_by_membership_id", U(), nullable=False),
        sa.Column("requested_by_user_id", U(), nullable=False),
        sa.Column("source_locale", sa.String(20), nullable=False),
        sa.Column("target_locale", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("total_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_sku_id", U(), nullable=True),
        sa.Column("current_sku_name", sa.String(500), nullable=True),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("provider_version", sa.String(120), nullable=False),
        sa.Column(
            "failure_details",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('INCREMENTAL', 'FULL_REBUILD')",
            name="ck_catalog_translation_jobs_mode_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_catalog_translation_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "total_skus >= 0",
            name="ck_catalog_translation_jobs_total_skus_nonnegative",
        ),
        sa.CheckConstraint(
            "processed_skus >= 0 AND processed_skus <= total_skus",
            name="ck_catalog_translation_jobs_processed_skus_valid",
        ),
        sa.CheckConstraint(
            "failed_skus >= 0",
            name="ck_catalog_translation_jobs_failed_skus_nonnegative",
        ),
        sa.CheckConstraint(
            "source_locale <> target_locale",
            name="ck_catalog_translation_jobs_source_target_locale_different",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_translation_jobs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_catalog_translation_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_catalog_translation_jobs_requested_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_translation_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_jobs_tenant_identity",
        ),
    )
    op.create_index(
        "ix_catalog_translation_jobs_tenant_created",
        "catalog_translation_jobs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_catalog_translation_jobs_active_tenant_locale",
        "catalog_translation_jobs",
        ["tenant_id", "target_locale"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
    )

    _enable_tenant_rls(
        "catalog_sku_translations",
        "catalog_sku_translations_tenant_isolation",
    )
    _enable_tenant_rls(
        "catalog_translation_jobs",
        "catalog_translation_jobs_tenant_isolation",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_catalog_translation_jobs_active_tenant_locale",
        table_name="catalog_translation_jobs",
    )
    op.drop_index(
        "ix_catalog_translation_jobs_tenant_created",
        table_name="catalog_translation_jobs",
    )
    op.drop_table("catalog_translation_jobs")
    op.drop_index(
        "ix_catalog_sku_translations_tenant_category_locale",
        table_name="catalog_sku_translations",
    )
    op.drop_index(
        "ix_catalog_sku_translations_tenant_locale",
        table_name="catalog_sku_translations",
    )
    op.drop_table("catalog_sku_translations")
