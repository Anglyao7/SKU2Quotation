"""Add category-level child pricing and quote visitor attribution.

The child pricing table stores a percentage (not a fixed price), preserving
different prices for every SKU in a category.  Quote attribution is kept on
the immutable draft/order rows so the parent can inspect country and final
amounts without gaining mutation rights over a child-owned request.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260827_0114"
down_revision = "20260826_0113"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _enable_rls(table: str, policy: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{policy}" ON "{table}" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def upgrade() -> None:
    op.create_table(
        "subaccount_category_price_overrides",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("membership_id", _uuid(), nullable=False),
        sa.Column("category_id", _uuid(), nullable=False),
        sa.Column("markup_percent", sa.Numeric(12, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_subaccount_category_price_override_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_subaccount_category_price_override_category",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "membership_id",
            "category_id",
            name="uq_subaccount_category_price_override",
        ),
        sa.CheckConstraint("markup_percent >= 0", name="category_markup_nonnegative"),
        sa.CheckConstraint("markup_percent <= 100000", name="category_markup_reasonable"),
    )
    op.create_index(
        "ix_subaccount_category_price_overrides_tenant_membership",
        "subaccount_category_price_overrides",
        ["tenant_id", "membership_id"],
    )
    _enable_rls(
        "subaccount_category_price_overrides",
        "subaccount_category_price_overrides_tenant_isolation",
    )

    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.add_column(sa.Column("visitor_country_code", sa.String(8), nullable=True))
    with op.batch_alter_table("storefront_order_records") as batch:
        batch.add_column(sa.Column("visitor_country_code", sa.String(8), nullable=True))
    op.create_index(
        "ix_public_quote_drafts_tenant_visitor_country",
        "public_quote_drafts",
        ["tenant_id", "visitor_country_code", "created_at"],
    )
    op.create_index(
        "ix_storefront_order_records_tenant_visitor_country",
        "storefront_order_records",
        ["tenant_id", "visitor_country_code", "confirmed_at"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "subaccount_category_price_overrides_tenant_isolation" '
            'ON "subaccount_category_price_overrides"'
        )
    op.drop_index(
        "ix_storefront_order_records_tenant_visitor_country",
        table_name="storefront_order_records",
    )
    op.drop_index(
        "ix_public_quote_drafts_tenant_visitor_country",
        table_name="public_quote_drafts",
    )
    with op.batch_alter_table("storefront_order_records") as batch:
        batch.drop_column("visitor_country_code")
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.drop_column("visitor_country_code")
    op.drop_index(
        "ix_subaccount_category_price_overrides_tenant_membership",
        table_name="subaccount_category_price_overrides",
    )
    op.drop_table("subaccount_category_price_overrides")
