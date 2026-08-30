"""Add tenant-owned HTML pages to the public storefront navigation.

Revision ID: 20260830_0121
Revises: 20260830_0120
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260830_0121"
down_revision = "20260830_0120"
branch_labels = None
depends_on = None


def _enable_tenant_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "storefront_custom_pages" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "storefront_custom_pages" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "storefront_custom_pages_tenant_isolation" '
        'ON "storefront_custom_pages" '
        f"FOR ALL USING (tenant_id = {tenant}) "
        f"WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    op.create_table(
        "storefront_custom_pages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("object_key", sa.String(length=1000), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("sort_order >= 0", name="ck_storefront_custom_pages_sort_order_nonnegative"),
        sa.CheckConstraint("byte_size > 0", name="ck_storefront_custom_pages_byte_size_positive"),
        sa.CheckConstraint("version >= 1", name="ck_storefront_custom_pages_version_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_storefront_custom_pages_tenant_slug"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_storefront_custom_pages_tenant_identity"),
    )
    op.create_index(
        "ix_storefront_custom_pages_tenant_navigation",
        "storefront_custom_pages",
        ["tenant_id", "enabled", "sort_order"],
        unique=False,
    )
    _enable_tenant_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "storefront_custom_pages_tenant_isolation" '
            'ON "storefront_custom_pages"'
        )
    op.drop_index(
        "ix_storefront_custom_pages_tenant_navigation",
        table_name="storefront_custom_pages",
    )
    op.drop_table("storefront_custom_pages")
