"""Persist administrator catalog translation overrides.

Revision ID: 20260830_0124
Revises: 20260830_0123
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260830_0124"
down_revision = "20260830_0123"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _enable_tenant_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(
        'ALTER TABLE "catalog_translation_overrides" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        'ALTER TABLE "catalog_translation_overrides" FORCE ROW LEVEL SECURITY'
    )
    op.execute(
        'CREATE POLICY "catalog_translation_overrides_tenant_isolation" '
        'ON "catalog_translation_overrides" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    op.create_table(
        "catalog_translation_overrides",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_locale", sa.String(length=20), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "values",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("updated_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "entity_type IN ('PRODUCT', 'SKU')",
            name="ck_catalog_translation_overrides_entity_type_allowed",
        ),
        sa.CheckConstraint(
            "length(source_hash) = 64",
            name="ck_catalog_translation_overrides_source_hash_sha256_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_translation_overrides_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "target_locale",
            "entity_type",
            "entity_id",
            name="uq_catalog_translation_overrides_tenant_locale_entity",
        ),
    )
    op.create_index(
        "ix_catalog_translation_overrides_tenant_locale",
        "catalog_translation_overrides",
        ["tenant_id", "target_locale"],
    )
    _enable_tenant_rls()


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_translation_overrides_tenant_locale",
        table_name="catalog_translation_overrides",
    )
    op.drop_table("catalog_translation_overrides")
