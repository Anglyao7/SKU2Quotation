"""Track aggregated public storefront search terms.

Revision ID: 20260826_0113
Revises: 20260826_0112
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260826_0113"
down_revision = "20260826_0112"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _platform_admin_expression() -> str:
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
    return (
        "EXISTS (SELECT 1 FROM users platform_user "
        f"WHERE platform_user.id = {user_id} "
        "AND platform_user.status = 'active' "
        "AND platform_user.is_platform_admin = TRUE)"
    )


def _enable_tenant_policy() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(
        'ALTER TABLE "storefront_search_term_daily" ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        'ALTER TABLE "storefront_search_term_daily" FORCE ROW LEVEL SECURITY'
    )
    op.execute(
        'CREATE POLICY "storefront_search_term_daily_tenant_isolation" '
        'ON "storefront_search_term_daily" FOR ALL '
        f"USING (tenant_id = {tenant_id}) "
        f"WITH CHECK (tenant_id = {tenant_id})"
    )
    op.execute(
        'CREATE POLICY "storefront_search_term_daily_platform_read" '
        'ON "storefront_search_term_daily" FOR SELECT '
        f"USING (tenant_id = {tenant_id} OR {_platform_admin_expression()})"
    )


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    op.create_table(
        "storefront_search_term_daily",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("searched_on", sa.Date(), nullable=False),
        sa.Column("term_normalized", sa.String(200), nullable=False),
        sa.Column("term_display", sa.String(200), nullable=False),
        sa.Column("search_count", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "last_searched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_search_term_daily_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_search_term_daily_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "searched_on",
            "term_normalized",
            name="uq_storefront_search_term_daily_term",
        ),
    )
    op.create_index(
        "ix_storefront_search_term_daily_tenant_date",
        "storefront_search_term_daily",
        ["tenant_id", "searched_on"],
    )
    op.create_index(
        "ix_storefront_search_term_daily_tenant_count",
        "storefront_search_term_daily",
        ["tenant_id", "search_count"],
    )
    _enable_tenant_policy()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "storefront_search_term_daily_platform_read" '
            'ON "storefront_search_term_daily"'
        )
        op.execute(
            'DROP POLICY IF EXISTS "storefront_search_term_daily_tenant_isolation" '
            'ON "storefront_search_term_daily"'
        )
    op.drop_index(
        "ix_storefront_search_term_daily_tenant_count",
        table_name="storefront_search_term_daily",
    )
    op.drop_index(
        "ix_storefront_search_term_daily_tenant_date",
        table_name="storefront_search_term_daily",
    )
    op.drop_table("storefront_search_term_daily")
