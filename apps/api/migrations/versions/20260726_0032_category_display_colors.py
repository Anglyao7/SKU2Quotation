"""Add merchant-customizable primary category display colors.

Revision ID: 20260726_0032
Revises: 20260726_0031
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0032"
down_revision = "20260726_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_categories",
        sa.Column("display_color", sa.String(7), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_categories", "display_color")
