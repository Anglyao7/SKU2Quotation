"""Add durable product image enhancement tasks and review items."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_0094"
down_revision = "20260816_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_enhancement_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("size", sa.String(length=32), nullable=False, server_default="1024x1024"),
        sa.Column("output_format", sa.String(length=20), nullable=False, server_default="url"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="QUEUED"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("output_format = 'url'", name="output_format_allowed"),
        sa.CheckConstraint("total_items >= 0", name="total_items_nonnegative"),
        sa.CheckConstraint("completed_items >= 0", name="completed_items_nonnegative"),
        sa.CheckConstraint("failed_items >= 0", name="failed_items_nonnegative"),
        sa.CheckConstraint("cancelled_items >= 0", name="cancelled_items_nonnegative"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_image_enhancement_tasks_tenant_identity"),
    )
    op.create_index(
        "ix_image_enhancement_tasks_tenant_updated",
        "image_enhancement_tasks",
        ["tenant_id", "updated_at"],
    )
    op.create_index(
        "ix_image_enhancement_tasks_active",
        "image_enhancement_tasks",
        ["tenant_id", "status"],
    )
    op.create_table(
        "image_enhancement_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("source_image_id", sa.Uuid(), nullable=True),
        sa.Column("sku_ids", sa.JSON(), nullable=False),
        sa.Column("sku_snapshot", sa.JSON(), nullable=False),
        sa.Column("product_name", sa.String(length=500), nullable=False),
        sa.Column("source_image_url", sa.String(length=2000), nullable=False),
        sa.Column("source_object_key", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="QUEUED"),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("result_url", sa.String(length=2000), nullable=True),
        sa.Column("result_object_key", sa.String(length=1024), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'APPLIED')",
            name="review_status_allowed",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["image_enhancement_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_image_id"], ["product_images.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "source_image_id", name="uq_image_enhancement_items_source"),
    )
    op.create_index(
        "ix_image_enhancement_items_task_status",
        "image_enhancement_items",
        ["task_id", "status"],
    )
    op.create_index(
        "ix_image_enhancement_items_tenant_product",
        "image_enhancement_items",
        ["tenant_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_enhancement_items_tenant_product", table_name="image_enhancement_items")
    op.drop_index("ix_image_enhancement_items_task_status", table_name="image_enhancement_items")
    op.drop_table("image_enhancement_items")
    op.drop_index("ix_image_enhancement_tasks_active", table_name="image_enhancement_tasks")
    op.drop_index("ix_image_enhancement_tasks_tenant_updated", table_name="image_enhancement_tasks")
    op.drop_table("image_enhancement_tasks")
