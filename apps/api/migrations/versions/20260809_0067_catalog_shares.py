"""Add tenant-scoped catalog share links.

Revision ID: 20260809_0067
Revises: 20260809_0066
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260809_0067"
down_revision = "20260809_0066"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)
JSON_DOCUMENT = sa.JSON().with_variant(JSONB(none_as_null=True), "postgresql")


def upgrade() -> None:
    op.create_table(
        "catalog_shares",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("share_token", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("product_ids", JSON_DOCUMENT, nullable=False),
        sa.Column("category_id", U(), nullable=True),
        sa.Column("category_path", sa.String(500), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", U(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('PRODUCTS', 'CATEGORY')",
            name="ck_catalog_shares_target_type_allowed",
        ),
        sa.CheckConstraint(
            "item_count > 0",
            name="ck_catalog_shares_item_count_positive",
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 64",
            name="ck_catalog_shares_fingerprint_sha256_length",
        ),
        sa.CheckConstraint(
            "(target_type = 'PRODUCTS' AND category_id IS NULL) OR "
            "(target_type = 'CATEGORY' AND category_id IS NOT NULL)",
            name="ck_catalog_shares_target_shape_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_shares_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_catalog_shares_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_catalog_shares_tenant_category",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_shares"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_catalog_shares_tenant_identity"
        ),
        sa.UniqueConstraint("share_token", name="uq_catalog_shares_token"),
        sa.UniqueConstraint(
            "tenant_id",
            "fingerprint",
            name="uq_catalog_shares_tenant_fingerprint",
        ),
    )
    op.create_index(
        "ix_catalog_shares_tenant_created",
        "catalog_shares",
        ["tenant_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "catalog_shares" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "catalog_shares" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "catalog_shares_tenant_isolation" '
            'ON "catalog_shares" FOR ALL '
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_shares_tenant_created", table_name="catalog_shares"
    )
    op.drop_table("catalog_shares")
