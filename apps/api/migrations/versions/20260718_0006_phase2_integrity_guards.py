"""Add final Phase 2 supplier and product-image integrity guards.

Revision ID: 20260718_0006
Revises: 20260718_0005
Requirements: DB-PROD-001, DB-SUP-002
"""
from alembic import op


revision = "20260718_0006"
down_revision = "20260718_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suppliers") as batch_op:
        batch_op.create_check_constraint(
            "ck_suppliers_status_allowed",
            "status IN ('ACTIVE', 'INACTIVE', 'BLOCKED', 'ARCHIVED')",
        )
        batch_op.create_check_constraint(
            "ck_suppliers_risk_level_allowed",
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'UNKNOWN')",
        )
        batch_op.create_check_constraint("ck_suppliers_version_positive", "version >= 1")
        batch_op.create_check_constraint(
            "ck_suppliers_active_skus_nonnegative", "active_skus >= 0"
        )
        batch_op.create_check_constraint(
            "ck_suppliers_country_code_format",
            "country_code IS NULL OR (length(country_code) = 2 AND country_code = UPPER(country_code))",
        )
    with op.batch_alter_table("product_images") as batch_op:
        batch_op.create_check_constraint(
            "ck_product_images_image_role_allowed",
            "image_role IN ('MAIN', 'GALLERY', 'DETAIL', 'PACKAGING', 'CERTIFICATE')",
        )


def downgrade() -> None:
    with op.batch_alter_table("product_images") as batch_op:
        batch_op.drop_constraint("ck_product_images_image_role_allowed", type_="check")
    with op.batch_alter_table("suppliers") as batch_op:
        for constraint in (
            "ck_suppliers_country_code_format",
            "ck_suppliers_active_skus_nonnegative",
            "ck_suppliers_version_positive",
            "ck_suppliers_risk_level_allowed",
            "ck_suppliers_status_allowed",
        ):
            batch_op.drop_constraint(constraint, type_="check")
