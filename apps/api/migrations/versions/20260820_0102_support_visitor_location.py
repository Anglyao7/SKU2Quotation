"""Store country and timezone metadata for storefront support visitors."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260820_0102"
down_revision = "20260816_0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("storefront_chat_conversations")
    }
    additions = []
    if "visitor_ip" not in columns:
        additions.append(sa.Column("visitor_ip", sa.String(length=45), nullable=True))
    if "visitor_country_code" not in columns:
        additions.append(
            sa.Column("visitor_country_code", sa.String(length=2), nullable=True)
        )
    if "visitor_timezone" not in columns:
        additions.append(
            sa.Column("visitor_timezone", sa.String(length=80), nullable=True)
        )
    if not additions:
        return
    with op.batch_alter_table("storefront_chat_conversations") as batch:
        for column in additions:
            batch.add_column(column)


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("storefront_chat_conversations")
    }
    removals = [
        name
        for name in ("visitor_timezone", "visitor_country_code", "visitor_ip")
        if name in columns
    ]
    if not removals:
        return
    with op.batch_alter_table("storefront_chat_conversations") as batch:
        for name in removals:
            batch.drop_column(name)
