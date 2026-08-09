"""Add merchant subscription levels and expiry dates.

Revision ID: 20260809_0065
Revises: 20260809_0064
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0065"
down_revision = "20260809_0064"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "tenant_subscriptions",
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "subscription_tier",
            sa.String(20),
            nullable=False,
            server_default="TRIAL",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "subscription_tier IN ('TRIAL', 'STANDARD', 'SILVER', 'ELITE')",
            name="tier_allowed",
        ),
        sa.CheckConstraint(
            "expires_at > started_at",
            name="expiry_after_start",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_index(
        "ix_tenant_subscriptions_tier_expiry",
        "tenant_subscriptions",
        ["subscription_tier", "expires_at"],
    )
    expiry_sql = (
        "CURRENT_TIMESTAMP + INTERVAL '1 year'"
        if op.get_bind().dialect.name == "postgresql"
        else "datetime(CURRENT_TIMESTAMP, '+1 year')"
    )
    op.execute(
        sa.text(
            "INSERT INTO tenant_subscriptions "
            "(tenant_id, subscription_tier, started_at, expires_at, created_at, updated_at) "
            "SELECT id, 'STANDARD', CURRENT_TIMESTAMP, "
            f"{expiry_sql}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM tenants"
        )
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
        platform_admin = (
            "EXISTS (SELECT 1 FROM users platform_user "
            f"WHERE platform_user.id = {user_id} "
            "AND platform_user.status = 'active' "
            "AND platform_user.is_platform_admin = TRUE)"
        )
        op.execute(
            'ALTER TABLE "tenant_subscriptions" ENABLE ROW LEVEL SECURITY'
        )
        op.execute(
            'ALTER TABLE "tenant_subscriptions" FORCE ROW LEVEL SECURITY'
        )
        op.execute(
            'CREATE POLICY "tenant_subscriptions_tenant_isolation" '
            'ON "tenant_subscriptions" FOR ALL '
            f"USING (tenant_id = {tenant_id} OR {platform_admin}) "
            f"WITH CHECK (tenant_id = {tenant_id} OR {platform_admin})"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_subscriptions_tier_expiry",
        table_name="tenant_subscriptions",
    )
    op.drop_table("tenant_subscriptions")
