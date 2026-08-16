"""Add the tenant dashboard statistics read model.

The dashboard used to count products, images, suppliers and trade-flow rows on
every page load.  This migration adds a small denormalized table that is
rebuilt only after a relevant write (or when a new day starts).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_0097"
down_revision = "20260816_0096"
branch_labels = None
depends_on = None


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def _enable_tenant_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "dashboard_statistics" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "dashboard_statistics" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "dashboard_statistics_tenant_isolation" '
        'ON "dashboard_statistics" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    op.create_table(
        "dashboard_statistics",
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("statistics_date", sa.Date(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active_skus", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_products", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_suppliers", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("today_inquiries", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("open_inquiries", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("pending_quotes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("pending_reviews", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("approved_images", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sourced_products", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("priced_products", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "membership_metrics",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("active_skus >= 0", name="active_skus_nonnegative"),
        sa.CheckConstraint("active_products >= 0", name="active_products_nonnegative"),
        sa.CheckConstraint("active_suppliers >= 0", name="active_suppliers_nonnegative"),
        sa.CheckConstraint("today_inquiries >= 0", name="today_inquiries_nonnegative"),
        sa.CheckConstraint("open_inquiries >= 0", name="open_inquiries_nonnegative"),
        sa.CheckConstraint("pending_quotes >= 0", name="pending_quotes_nonnegative"),
        sa.CheckConstraint("pending_reviews >= 0", name="pending_reviews_nonnegative"),
        sa.CheckConstraint("approved_images >= 0", name="approved_images_nonnegative"),
        sa.CheckConstraint("sourced_products >= 0", name="sourced_products_nonnegative"),
        sa.CheckConstraint("priced_products >= 0", name="priced_products_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_dashboard_statistics_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_dashboard_statistics"),
    )
    # Seed existing tenants so the first post-deploy dashboard request only
    # refreshes a row instead of racing to create it.  New tenants are created
    # lazily by the same read path.
    op.execute(
        sa.text(
            "INSERT INTO dashboard_statistics (tenant_id, created_at, updated_at) "
            "SELECT id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM tenants WHERE deleted_at IS NULL"
        )
    )
    _enable_tenant_rls()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "dashboard_statistics_tenant_isolation" '
            'ON "dashboard_statistics"'
        )
    op.drop_table("dashboard_statistics")
