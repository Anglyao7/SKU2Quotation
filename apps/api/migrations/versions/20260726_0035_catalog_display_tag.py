"""Add an explicit storefront display tag to public catalog offers.

Revision ID: 20260726_0035
Revises: 20260726_0034
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260726_0035"
down_revision = "20260726_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "public_catalog_offers",
        sa.Column("display_tag", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("public_catalog_offers", "display_tag")
