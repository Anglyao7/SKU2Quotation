"""Allow cancellation of an individual running enhancement item."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_0095"
down_revision = "20260816_0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "image_enhancement_items",
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("image_enhancement_items", "cancellation_requested")
