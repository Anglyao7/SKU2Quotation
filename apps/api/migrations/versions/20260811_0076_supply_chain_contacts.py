"""Add supply-chain contact details to suppliers.

Revision ID: 20260811_0076
Revises: 20260810_0075
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260811_0076"
down_revision = "20260810_0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("suppliers") as batch:
        batch.add_column(sa.Column("contact_name", sa.String(200), nullable=True))
        batch.add_column(sa.Column("phone", sa.String(100), nullable=True))
        batch.add_column(sa.Column("email", sa.String(320), nullable=True))
        batch.add_column(sa.Column("whatsapp", sa.String(100), nullable=True))
        batch.add_column(sa.Column("wechat", sa.String(100), nullable=True))
        batch.add_column(sa.Column("country_region", sa.String(200), nullable=True))
        batch.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch.add_column(sa.Column("business_scope", sa.Text(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("suppliers") as batch:
        batch.drop_column("notes")
        batch.drop_column("business_scope")
        batch.drop_column("address")
        batch.drop_column("country_region")
        batch.drop_column("wechat")
        batch.drop_column("whatsapp")
        batch.drop_column("email")
        batch.drop_column("phone")
        batch.drop_column("contact_name")
