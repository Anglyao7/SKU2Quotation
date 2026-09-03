"""Allow one product to appear in multiple categories.

Revision ID: 20260903_0130
Revises: 20260831_0129
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260903_0130"
down_revision = "20260831_0129"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    offline = op.get_context().as_sql
    if offline or "product_category_memberships" not in _tables():
        op.create_table(
            "product_category_memberships",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("product_id", sa.Uuid(), nullable=False),
            sa.Column("category_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_product_category_memberships_tenant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "product_id"],
                ["products.tenant_id", "products.id"],
                name="fk_product_category_memberships_product",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "category_id"],
                ["product_categories.tenant_id", "product_categories.id"],
                name="fk_product_category_memberships_category",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "product_id",
                "category_id",
                name="uq_product_category_memberships_assignment",
            ),
            if_not_exists=True,
        )
        op.create_index(
            "ix_product_category_memberships_tenant_category_product",
            "product_category_memberships",
            ["tenant_id", "category_id", "product_id"],
            unique=False,
            if_not_exists=True,
        )
        op.create_index(
            "ix_product_category_memberships_tenant_product",
            "product_category_memberships",
            ["tenant_id", "product_id"],
            unique=False,
            if_not_exists=True,
        )
    if op.get_bind().dialect.name == "postgresql":
        tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute(
            'ALTER TABLE "product_category_memberships" ENABLE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "product_category_memberships" FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            'DROP POLICY IF EXISTS "product_category_memberships_tenant_isolation" '
            'ON "product_category_memberships"'
        )
        op.execute(
            'CREATE POLICY "product_category_memberships_tenant_isolation" '
            'ON "product_category_memberships" FOR ALL '
            f"USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})"
        )


def downgrade() -> None:
    if not op.get_context().as_sql and "product_category_memberships" not in _tables():
        return
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "product_category_memberships_tenant_isolation" '
            'ON "product_category_memberships"'
        )
    op.drop_table("product_category_memberships")
