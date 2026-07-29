"""Add the merchant-controlled position of the all-products storefront entry.

Revision ID: 20260729_0039
Revises: 20260728_0038
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260729_0039"
down_revision = "20260728_0038"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_tenant_public_profiles_all_products_position_nonnegative"


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "all_products_position",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.create_check_constraint(
            CONSTRAINT_NAME,
            "all_products_position >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.drop_column("all_products_position")
