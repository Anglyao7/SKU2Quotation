"""Add platform-wide merchant usage analytics and storefront visits.

Revision ID: 20260826_0111
Revises: 20260825_0110
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260826_0111"
down_revision = "20260825_0110"
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


def _platform_read_policy_name(policy_name: str) -> str:
    return f"{policy_name}_platform_read"


def _create_tenant_policy(table_name: str, policy_name: str) -> None:
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(
        f'CREATE POLICY "{policy_name}" ON "{table_name}" FOR ALL '
        f"USING (tenant_id = {tenant}) "
        f"WITH CHECK (tenant_id = {tenant})"
    )


def _replace_tenant_policy(table_name: str, policy_name: str) -> None:
    """Keep tenant writes and add a read-only platform-admin policy.

    The dashboard only needs to read aggregate data.  Keeping the original
    tenant-scoped ``FOR ALL`` policy means a platform-admin context cannot
    accidentally mutate merchant event rows through this reporting endpoint.
    """

    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    platform_admin = _platform_admin_expression()
    read_policy_name = _platform_read_policy_name(policy_name)
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    op.execute(f'DROP POLICY IF EXISTS "{read_policy_name}" ON "{table_name}"')
    _create_tenant_policy(table_name, policy_name)
    op.execute(
        f'CREATE POLICY "{read_policy_name}" ON "{table_name}" FOR SELECT '
        f"USING (tenant_id = {tenant} OR {platform_admin})"
    )


def _enable_tenant_policy(table_name: str, policy_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    platform_admin = _platform_admin_expression()
    read_policy_name = _platform_read_policy_name(policy_name)
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    _create_tenant_policy(table_name, policy_name)
    op.execute(
        f'CREATE POLICY "{read_policy_name}" ON "{table_name}" FOR SELECT '
        f"USING (tenant_id = {tenant} OR {platform_admin})"
    )


def _restore_tenant_policy(table_name: str, policy_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'DROP POLICY IF EXISTS "{_platform_read_policy_name(policy_name)}" ON "{table_name}"')
    op.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table_name}"')
    _create_tenant_policy(table_name, policy_name)


def upgrade() -> None:
    uuid_type = sa.Uuid(as_uuid=True)
    audit = [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]

    op.create_table(
        "storefront_visit_events",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("visitor_key", sa.String(64), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="ZZ"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        *audit,
        sa.CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code)",
            name="country_code_format",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_storefront_visit_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_storefront_visit_events_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id", "event_id", name="uq_storefront_visit_events_event"
        ),
    )
    op.create_index(
        "ix_storefront_visit_events_tenant_occurred",
        "storefront_visit_events",
        ["tenant_id", "occurred_at"],
    )
    op.create_index(
        "ix_storefront_visit_events_tenant_visitor_occurred",
        "storefront_visit_events",
        ["tenant_id", "visitor_key", "occurred_at"],
    )

    op.create_table(
        "tenant_usage_daily",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", uuid_type, nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("image_search_count", sa.BigInteger(), nullable=False, server_default="0"),
        *audit,
        sa.CheckConstraint(
            "image_search_count >= 0", name="image_search_count_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_tenant_usage_daily_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "usage_date", name="uq_tenant_usage_daily_tenant_date"
        ),
    )
    op.create_index(
        "ix_tenant_usage_daily_tenant_date",
        "tenant_usage_daily",
        ["tenant_id", "usage_date"],
    )

    _enable_tenant_policy(
        "storefront_visit_events", "storefront_visit_events_tenant_isolation"
    )
    _enable_tenant_policy(
        "tenant_usage_daily", "tenant_usage_daily_tenant_isolation"
    )

    # Existing event tables were created before the platform dashboard.  Keep
    # their tenant isolation for normal merchants while allowing the platform
    # administrator to run aggregate-only queries across all tenants.
    for table_name, policy_name in (
        ("storefront_product_view_events", "storefront_product_view_events_tenant_isolation"),
        ("storefront_product_view_daily", "storefront_product_view_daily_tenant_isolation"),
        ("public_quote_drafts", "public_quote_drafts_tenant_isolation"),
        ("quotations", "quotations_tenant_isolation"),
        ("image_searches", "image_searches_tenant_isolation"),
        ("storefront_chat_conversations", "storefront_chat_conversations_tenant_isolation"),
        ("storefront_chat_messages", "storefront_chat_messages_tenant_isolation"),
    ):
        _replace_tenant_policy(table_name, policy_name)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table_name, policy_name in (
            ("storefront_product_view_events", "storefront_product_view_events_tenant_isolation"),
            ("storefront_product_view_daily", "storefront_product_view_daily_tenant_isolation"),
            ("public_quote_drafts", "public_quote_drafts_tenant_isolation"),
            ("quotations", "quotations_tenant_isolation"),
            ("image_searches", "image_searches_tenant_isolation"),
            ("storefront_chat_conversations", "storefront_chat_conversations_tenant_isolation"),
            ("storefront_chat_messages", "storefront_chat_messages_tenant_isolation"),
        ):
            _restore_tenant_policy(table_name, policy_name)
    op.drop_index(
        "ix_tenant_usage_daily_tenant_date", table_name="tenant_usage_daily"
    )
    op.drop_table("tenant_usage_daily")
    op.drop_index(
        "ix_storefront_visit_events_tenant_visitor_occurred",
        table_name="storefront_visit_events",
    )
    op.drop_index(
        "ix_storefront_visit_events_tenant_occurred",
        table_name="storefront_visit_events",
    )
    op.drop_table("storefront_visit_events")
