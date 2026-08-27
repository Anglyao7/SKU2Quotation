"""Add concrete SKU-level child-account price overrides.

Product and category rules remain useful defaults, but a reseller may need a
different price for each variant of one product.  This table stores that most
specific rule without changing the owner's source offer.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260827_0115"
down_revision = "20260827_0114"
branch_labels = None
depends_on = None


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
        "subaccount_sku_price_overrides",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("membership_id", _uuid(), nullable=False),
        sa.Column("sku_id", _uuid(), nullable=False),
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
            name="fk_subaccount_sku_price_override_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_subaccount_sku_price_override_sku",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "membership_id",
            "sku_id",
            name="uq_subaccount_sku_price_override",
        ),
        sa.CheckConstraint(
            "pricing_mode IN ('MARKUP_PERCENT', 'FIXED_PRICE')",
            name="sku_pricing_mode_allowed",
        ),
        sa.CheckConstraint("value >= 0", name="sku_override_value_nonnegative"),
    )
    op.create_index(
        "ix_subaccount_sku_price_overrides_tenant_membership",
        "subaccount_sku_price_overrides",
        ["tenant_id", "membership_id"],
    )
    op.create_index(
        "ix_subaccount_sku_price_overrides_tenant_sku",
        "subaccount_sku_price_overrides",
        ["tenant_id", "sku_id"],
    )
    _enable_rls(
        "subaccount_sku_price_overrides",
        "subaccount_sku_price_overrides_tenant_isolation",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            'DROP POLICY IF EXISTS "subaccount_sku_price_overrides_tenant_isolation" '
            'ON "subaccount_sku_price_overrides"'
        )
    op.drop_index(
        "ix_subaccount_sku_price_overrides_tenant_sku",
        table_name="subaccount_sku_price_overrides",
    )
    op.drop_index(
        "ix_subaccount_sku_price_overrides_tenant_membership",
        table_name="subaccount_sku_price_overrides",
    )
    op.drop_table("subaccount_sku_price_overrides")
