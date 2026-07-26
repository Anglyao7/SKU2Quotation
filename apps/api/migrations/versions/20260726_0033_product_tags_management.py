"""Add product tags management table.

Revision ID: 20260726_0033
Revises: 20260726_0032
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0033"
down_revision = "20260726_0032"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "product_tags",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False, comment="标签显示名称"),
        sa.Column("normalized_name", sa.String(80), nullable=False, comment="标签规范化名称（小写）用于去重"),
        sa.Column("description", sa.Text(), nullable=True, comment="标签说明"),
        sa.Column("category", sa.String(50), nullable=True, comment="标签分类：状态/特性/场景/优势等"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0", comment="使用次数"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "normalized_name", name="uq_product_tags_tenant_normalized_name"),
    )
    op.create_index(
        "idx_product_tags_tenant_name",
        "product_tags",
        ["tenant_id", "normalized_name"],
    )
    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "product_tags" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "product_tags" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "product_tags_tenant_isolation" ON "product_tags" '
            f"FOR ALL USING (tenant_id = {tenant}) "
            f"WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index("idx_product_tags_tenant_name", table_name="product_tags")
    op.drop_table("product_tags")
