"""Allow optional announcement titles and related SKU references.

Revision ID: 20260801_0046
Revises: 20260731_0045
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260801_0046"
down_revision = "20260731_0045"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("storefront_announcements") as batch:
        batch.alter_column(
            "title",
            existing_type=sa.String(length=200),
            nullable=True,
        )
        batch.add_column(
            sa.Column(
                "related_sku_ids",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "storefront_announcements" NO FORCE ROW LEVEL SECURITY')
    try:
        op.execute(
            "UPDATE storefront_announcements "
            "SET title = '' WHERE title IS NULL"
        )
    finally:
        if is_postgresql:
            op.execute('ALTER TABLE "storefront_announcements" FORCE ROW LEVEL SECURITY')
    with op.batch_alter_table("storefront_announcements") as batch:
        batch.drop_column("related_sku_ids")
        batch.alter_column(
            "title",
            existing_type=sa.String(length=200),
            nullable=False,
        )
