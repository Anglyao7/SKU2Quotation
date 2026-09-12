"""Add a merchant-controlled storefront price visibility setting."""
from alembic import op
import sqlalchemy as sa


revision = "20260912_0140"
down_revision = "20260909_0139"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("tenant_public_profiles") as batch:
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
