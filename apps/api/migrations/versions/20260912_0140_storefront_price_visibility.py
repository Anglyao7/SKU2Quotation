"""Add a merchant-controlled storefront price visibility setting."""
from alembic import op
import sqlalchemy as sa


revision = "20260912_0140"
down_revision = "20260909_0139"
branch_labels = depends_on = None


def upgrade():
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_public_profiles")
    }
    with op.batch_alter_table("tenant_public_profiles") as batch:
        # Recover cleanly from an interrupted SQLite batch migration where the
        # column addition persisted but the Alembic revision did not advance.
        if "storefront_prices_visible" not in existing_columns:
            batch.add_column(
                sa.Column(
                    "storefront_prices_visible",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )
        batch.alter_column("storefront_prices_visible", server_default=None)


def downgrade():
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("storefront_prices_visible")
