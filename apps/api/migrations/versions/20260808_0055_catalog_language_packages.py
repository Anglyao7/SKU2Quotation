"""Add versioned storefront catalog language packages.

Revision ID: 20260808_0055
Revises: 20260807_0054
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260808_0055"
down_revision = "20260807_0054"
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
        "catalog_language_packs",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("source_locale", sa.String(20), nullable=False),
        sa.Column("target_locale", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("public_url", sa.String(2000), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("storage_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "content_encoding",
            sa.String(20),
            nullable=False,
            server_default="gzip",
        ),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("product_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sku_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("provider_version", sa.String(120), nullable=False),
        sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_full_translation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_locale <> target_locale",
            name="ck_catalog_language_packs_source_target_locale_different",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_catalog_language_packs_version_positive",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_catalog_language_packs_content_sha256_length",
        ),
        sa.CheckConstraint(
            "length(source_digest) = 64",
            name="ck_catalog_language_packs_source_digest_length",
        ),
        sa.CheckConstraint(
            "length(storage_fingerprint) = 64",
            name="ck_catalog_language_packs_storage_fingerprint_length",
        ),
        sa.CheckConstraint(
            "byte_size >= 0",
            name="ck_catalog_language_packs_byte_size_nonnegative",
        ),
        sa.CheckConstraint(
            "product_count >= 0",
            name="ck_catalog_language_packs_product_count_nonnegative",
        ),
        sa.CheckConstraint(
            "sku_count >= 0",
            name="ck_catalog_language_packs_sku_count_nonnegative",
        ),
        sa.CheckConstraint(
            "category_count >= 0",
            name="ck_catalog_language_packs_category_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_language_packs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_language_packs"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_language_packs_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "target_locale",
            name="uq_catalog_language_packs_tenant_locale",
        ),
    )
    op.create_index(
        "ix_catalog_language_packs_tenant_published",
        "catalog_language_packs",
        ["tenant_id", "published_at"],
    )

    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.add_column(
            sa.Column("stage", sa.String(30), nullable=False, server_default="QUEUED")
        )
        batch.add_column(sa.Column("package_version", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "package_published",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("package_byte_size", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("source_cutoff_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            "stage IN ('QUEUED', 'PREPARING', 'TRANSLATING', 'PACKAGING', "
            "'UPLOADING', 'PUBLISHED', 'FAILED')",
        )

    op.execute(
        sa.text(
            "UPDATE catalog_translation_jobs SET stage = CASE "
            "WHEN status = 'SUCCEEDED' THEN 'PUBLISHED' "
            "WHEN status = 'FAILED' THEN 'FAILED' "
            "WHEN status = 'RUNNING' THEN 'TRANSLATING' "
            "ELSE 'QUEUED' END"
        )
    )

    _enable_tenant_rls(
        "catalog_language_packs",
        "catalog_language_packs_tenant_isolation",
    )


def downgrade() -> None:
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.drop_constraint(
            "ck_catalog_translation_jobs_stage_allowed",
            type_="check",
        )
        batch.drop_column("source_cutoff_at")
        batch.drop_column("package_byte_size")
        batch.drop_column("package_published")
        batch.drop_column("package_version")
        batch.drop_column("stage")

    op.drop_index(
        "ix_catalog_language_packs_tenant_published",
        table_name="catalog_language_packs",
    )
    op.drop_table("catalog_language_packs")
