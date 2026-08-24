"""Add child-account reseller pricing policies and product overrides.

Each child account is a reseller storefront.  The parent merchant's published
offer remains the source price; this migration stores only the child-specific
markup and optional product rules.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260823_0106"
down_revision = "20260823_0105"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


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
        "subaccount_pricing_policies",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("membership_id", _uuid(), nullable=False),
        sa.Column("markup_percent", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("hidden_product_ids", JSON_DOCUMENT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_subaccount_pricing_policy_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "membership_id", name="uq_subaccount_pricing_policy_membership"),
        sa.CheckConstraint("markup_percent >= 0", name="markup_percent_nonnegative"),
        sa.CheckConstraint("markup_percent <= 100000", name="markup_percent_reasonable"),
    )
    op.create_index(
        "ix_subaccount_pricing_policies_tenant_membership",
        "subaccount_pricing_policies",
        ["tenant_id", "membership_id"],
    )
    _enable_rls("subaccount_pricing_policies", "subaccount_pricing_policies_tenant_isolation")

    op.create_table(
        "subaccount_product_price_overrides",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("membership_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("pricing_mode", sa.String(30), nullable=False),
        sa.Column("value", sa.Numeric(20, 4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_subaccount_product_price_override_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_subaccount_product_price_override_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "membership_id", "product_id",
            name="uq_subaccount_product_price_override",
        ),
        sa.CheckConstraint(
            "pricing_mode IN ('MARKUP_PERCENT', 'FIXED_PRICE')",
            name="pricing_mode_allowed",
        ),
        sa.CheckConstraint("value >= 0", name="override_value_nonnegative"),
    )
    op.create_index(
        "ix_subaccount_product_price_overrides_tenant_membership",
        "subaccount_product_price_overrides",
        ["tenant_id", "membership_id"],
    )
    _enable_rls(
        "subaccount_product_price_overrides",
        "subaccount_product_price_overrides_tenant_isolation",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "subaccount_product_price_overrides_tenant_isolation" '
            'ON "subaccount_product_price_overrides"'
        )
        op.execute(
            'DROP POLICY IF EXISTS "subaccount_pricing_policies_tenant_isolation" '
            'ON "subaccount_pricing_policies"'
        )
    op.drop_index(
        "ix_subaccount_product_price_overrides_tenant_membership",
        table_name="subaccount_product_price_overrides",
    )
    op.drop_table("subaccount_product_price_overrides")
    op.drop_index(
        "ix_subaccount_pricing_policies_tenant_membership",
        table_name="subaccount_pricing_policies",
    )
    op.drop_table("subaccount_pricing_policies")
