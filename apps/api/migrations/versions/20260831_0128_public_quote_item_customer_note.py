"""Store customer notes for individual public quote items.

Revision ID: 20260831_0128
Revises: 20260831_0127
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_0128"
down_revision = "20260831_0127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("public_quote_draft_items")
    }
    if "customer_note" in columns:
        return
    with op.batch_alter_table("public_quote_draft_items") as batch:
        batch.add_column(sa.Column("customer_note", sa.Text(), nullable=True))


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("public_quote_draft_items")
    }
    if "customer_note" not in columns:
        return
    with op.batch_alter_table("public_quote_draft_items") as batch:
        batch.drop_column("customer_note")
