"""Persist customer-facing quote table columns."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_0098"
down_revision = "20260816_0097"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("public_quote_drafts")}
    if "quote_visible_columns" in columns:
        return
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.add_column(sa.Column("quote_visible_columns", JSON_DOCUMENT, nullable=True))


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("public_quote_drafts")}
    if "quote_visible_columns" not in columns:
        return
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.drop_column("quote_visible_columns")
