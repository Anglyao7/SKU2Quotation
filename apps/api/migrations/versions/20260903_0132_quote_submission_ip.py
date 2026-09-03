"""Retain quote submission IPs for bounded owner-side analysis.

Revision ID: 20260903_0132
Revises: 20260903_0131
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260903_0132"
down_revision = "20260903_0131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        op.add_column(
            "public_quote_drafts",
            sa.Column("visitor_ip_address", sa.String(length=45), nullable=True),
        )
        return
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("public_quote_drafts")
    }
    if "visitor_ip_address" not in columns:
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.add_column(
                sa.Column("visitor_ip_address", sa.String(length=45), nullable=True)
            )


def downgrade() -> None:
    if op.get_context().as_sql:
        op.drop_column("public_quote_drafts", "visitor_ip_address")
        return
    columns = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("public_quote_drafts")
    }
    if "visitor_ip_address" in columns:
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.drop_column("visitor_ip_address")
