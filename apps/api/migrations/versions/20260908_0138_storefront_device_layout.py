"""Add merchant-controlled responsive storefront category layout mode."""
from alembic import op
import sqlalchemy as sa

revision = "20260908_0138"
down_revision = "20260908_0137"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "storefront_category_layout_mode",
                sa.String(length=20),
                nullable=False,
                server_default="AUTO",
            )
        )
        batch.create_check_constraint(
            "storefront_category_layout_mode_allowed",
            "storefront_category_layout_mode IN ('AUTO', 'HORIZONTAL', 'VERTICAL')",
        )
        batch.alter_column(
            "storefront_category_layout_mode",
            server_default=None,
        )


def downgrade():
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_constraint(
            "storefront_category_layout_mode_allowed",
            type_="check",
        )
        batch.drop_column("storefront_category_layout_mode")
