"""Isolate reseller storefront presentation and custom pages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0136"
down_revision = "20260907_0135"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "subaccount_storefront_profiles",
        sa.Column("membership_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settings", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_subaccount_storefront_profiles_tenant_id", "subaccount_storefront_profiles", ["tenant_id"])
    with op.batch_alter_table("storefront_custom_pages") as batch:
        batch.add_column(sa.Column("owner_membership_id", sa.Uuid(), nullable=True))
        batch.drop_constraint("uq_storefront_custom_pages_tenant_slug", type_="unique")
        batch.create_unique_constraint("uq_storefront_custom_pages_account_slug", ["tenant_id", "owner_membership_id", "slug"])
        batch.create_foreign_key("fk_storefront_custom_pages_account", "memberships", ["tenant_id", "owner_membership_id"], ["tenant_id", "id"], ondelete="RESTRICT")
    op.create_index("uq_storefront_custom_pages_owner_slug", "storefront_custom_pages", ["tenant_id", "slug"], unique=True,
                    postgresql_where=sa.text("owner_membership_id IS NULL"), sqlite_where=sa.text("owner_membership_id IS NULL"))
    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute("ALTER TABLE subaccount_storefront_profiles ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE subaccount_storefront_profiles FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY subaccount_storefront_profiles_tenant_isolation ON subaccount_storefront_profiles FOR ALL USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})")


def downgrade():
    # Refuse a destructive downgrade when account pages would collide or lose
    # their ownership. Operators must export/migrate them explicitly first.
    if (op.get_bind().execute(sa.text("SELECT 1 FROM storefront_custom_pages WHERE owner_membership_id IS NOT NULL LIMIT 1")).first()
            or op.get_bind().execute(sa.text("SELECT 1 FROM subaccount_storefront_profiles LIMIT 1")).first()):
        raise RuntimeError("Export account storefront settings/pages before downgrading this migration")
    op.drop_index("uq_storefront_custom_pages_owner_slug", table_name="storefront_custom_pages")
    with op.batch_alter_table("storefront_custom_pages") as batch:
        batch.drop_constraint("fk_storefront_custom_pages_account", type_="foreignkey")
        batch.drop_constraint("uq_storefront_custom_pages_account_slug", type_="unique")
        batch.drop_column("owner_membership_id")
        batch.create_unique_constraint("uq_storefront_custom_pages_tenant_slug", ["tenant_id", "slug"])
    op.drop_table("subaccount_storefront_profiles")
