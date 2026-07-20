"""Add the Phase 2 direct category-cycle guard.

Revision ID: 20260718_0004
Revises: 20260718_0003
Requirement: DB-PROD-002
"""
from alembic import op


revision = "20260718_0004"
down_revision = "20260718_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("product_categories") as batch_op:
        batch_op.create_check_constraint(
            "ck_product_categories_not_self_parent",
            "parent_id IS NULL OR parent_id <> id",
        )


def downgrade() -> None:
    with op.batch_alter_table("product_categories") as batch_op:
        batch_op.drop_constraint(
            "ck_product_categories_not_self_parent", type_="check"
        )
