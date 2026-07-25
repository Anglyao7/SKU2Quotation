"""Add merchant-customizable storefront tag colors.

Revision ID: 20260726_0031
Revises: 20260726_0030
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0031"
down_revision = "20260726_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "public_catalog_offers",
        sa.Column("tag_color", sa.String(7), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("public_catalog_offers", "tag_color")
