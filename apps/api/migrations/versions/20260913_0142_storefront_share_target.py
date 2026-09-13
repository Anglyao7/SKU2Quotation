"""Allow sharing an entire published storefront."""

from __future__ import annotations

from alembic import op


revision = "20260913_0142"
down_revision = "20260913_0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_shares") as batch:
        batch.drop_constraint("ck_catalog_shares_target_type_allowed", type_="check")
        batch.drop_constraint("ck_catalog_shares_target_shape_valid", type_="check")
        batch.create_check_constraint(
            "ck_catalog_shares_target_type_allowed",
            "target_type IN ('PRODUCTS', 'CATEGORY', 'STOREFRONT')",
        )
        batch.create_check_constraint(
            "ck_catalog_shares_target_shape_valid",
            "(target_type IN ('PRODUCTS', 'STOREFRONT') AND category_id IS NULL) OR "
            "(target_type = 'CATEGORY' AND category_id IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("catalog_shares") as batch:
        batch.drop_constraint("ck_catalog_shares_target_type_allowed", type_="check")
        batch.drop_constraint("ck_catalog_shares_target_shape_valid", type_="check")
        batch.create_check_constraint(
            "ck_catalog_shares_target_type_allowed",
            "target_type IN ('PRODUCTS', 'CATEGORY')",
        )
        batch.create_check_constraint(
            "ck_catalog_shares_target_shape_valid",
            "(target_type = 'PRODUCTS' AND category_id IS NULL) OR "
            "(target_type = 'CATEGORY' AND category_id IS NOT NULL)",
        )
