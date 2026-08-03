"""Add observable background jobs for complete catalog deletion.

Revision ID: 20260802_0051
Revises: 20260802_0050
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0051"
down_revision = "20260802_0050"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "catalog_delete_jobs",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("requested_by_membership_id", U(), nullable=False),
        sa.Column("requested_by_user_id", U(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("stage", sa.String(40), nullable=False, server_default="QUEUED"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_products", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_skus", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "deleted_product_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "deleted_sku_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_catalog_delete_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_catalog_delete_jobs_progress_valid",
        ),
        sa.CheckConstraint(
            "total_products >= 0",
            name="ck_catalog_delete_jobs_total_products_nonnegative",
        ),
        sa.CheckConstraint(
            "total_skus >= 0",
            name="ck_catalog_delete_jobs_total_skus_nonnegative",
        ),
        sa.CheckConstraint(
            "deleted_product_count >= 0",
            name="ck_catalog_delete_jobs_deleted_product_count_nonnegative",
        ),
        sa.CheckConstraint(
            "deleted_sku_count >= 0",
            name="ck_catalog_delete_jobs_deleted_sku_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_catalog_delete_jobs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_catalog_delete_jobs_tenant_requester",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_catalog_delete_jobs_requested_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_delete_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_catalog_delete_jobs_tenant_identity",
        ),
    )
    op.create_index(
        "ix_catalog_delete_jobs_tenant_created",
        "catalog_delete_jobs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "uq_catalog_delete_jobs_active_tenant",
        "catalog_delete_jobs",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "status IN ('QUEUED', 'RUNNING') AND deleted_at IS NULL"
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "catalog_delete_jobs" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "catalog_delete_jobs" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "catalog_delete_jobs_tenant_isolation" '
            'ON "catalog_delete_jobs" '
            f"FOR ALL USING (tenant_id = {tenant}) "
            f"WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index(
        "uq_catalog_delete_jobs_active_tenant",
        table_name="catalog_delete_jobs",
    )
    op.drop_index(
        "ix_catalog_delete_jobs_tenant_created",
        table_name="catalog_delete_jobs",
    )
    op.drop_table("catalog_delete_jobs")
