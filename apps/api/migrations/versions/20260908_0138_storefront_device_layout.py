"""Add merchant-controlled responsive storefront category layout mode."""
from alembic import op
import sqlalchemy as sa

revision = "20260908_0138"
down_revision = "20260908_0137"
branch_labels = depends_on = None


def upgrade():
    existing_columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_public_profiles")
    }
    with op.batch_alter_table("tenant_public_profiles") as batch:
        # SQLite can leave ADD COLUMN applied when a later batch operation is
        # interrupted, while Alembic still points at the previous revision.
        # Re-running the migration must reuse that column instead of adding a
        # duplicate with the same name (which creates a circular reorder).
        if "storefront_category_layout_mode" not in existing_columns:
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
