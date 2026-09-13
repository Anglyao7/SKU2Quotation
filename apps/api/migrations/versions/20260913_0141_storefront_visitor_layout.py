"""Allow storefront visitors to choose the category layout."""

from alembic import op


revision = "20260913_0141"
down_revision = "20260912_0140"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_constraint(
            "storefront_category_layout_mode_allowed",
            type_="check",
        )
        batch.create_check_constraint(
            "storefront_category_layout_mode_allowed",
            "storefront_category_layout_mode IN ('AUTO', 'HORIZONTAL', 'VERTICAL', 'VISITOR')",
        )


def downgrade():
    # Existing VISITOR rows are converted to AUTO before restoring the old
    # constraint so a downgrade never leaves invalid data behind.
    op.execute(
        "UPDATE tenant_public_profiles "
        "SET storefront_category_layout_mode = 'AUTO' "
        "WHERE storefront_category_layout_mode = 'VISITOR'"
    )
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_constraint(
            "storefront_category_layout_mode_allowed",
            type_="check",
        )
        batch.create_check_constraint(
            "storefront_category_layout_mode_allowed",
            "storefront_category_layout_mode IN ('AUTO', 'HORIZONTAL', 'VERTICAL')",
        )
