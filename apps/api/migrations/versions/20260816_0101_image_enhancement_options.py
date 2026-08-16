"""Add ratio and named resolution controls to image enhancement tasks."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_0101"
down_revision = "20260816_0100"
branch_labels = None
depends_on = None


RATIO_CONSTRAINT = "ratio_allowed"
SIZE_CONSTRAINT = "size_allowed"


def upgrade() -> None:
    with op.batch_alter_table("image_enhancement_tasks") as batch:
        batch.add_column(
            sa.Column("ratio", sa.String(length=8), nullable=False, server_default="1:1")
        )
        batch.alter_column(
            "size",
            existing_type=sa.String(length=32),
            server_default="1K",
        )
        batch.create_check_constraint(
            RATIO_CONSTRAINT,
            "ratio IN ('1:1', '4:3', '3:4', '16:9', '9:16')",
        )
        # Keep the three pixel values accepted by the previous API so existing
        # tasks remain valid while new requests use 1K/2K/4K.
        batch.create_check_constraint(
            SIZE_CONSTRAINT,
            "size IN ('1K', '2K', '4K', '1024x1024', '1024x768', '768x1024')",
        )


def downgrade() -> None:
    with op.batch_alter_table("image_enhancement_tasks") as batch:
        batch.drop_constraint(SIZE_CONSTRAINT, type_="check")
        batch.drop_constraint(RATIO_CONSTRAINT, type_="check")
        batch.alter_column(
            "size",
            existing_type=sa.String(length=32),
            server_default="1024x1024",
        )
        batch.drop_column("ratio")
