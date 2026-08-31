"""Separate curated popular search terms from AI recommended questions.

Revision ID: 20260831_0127
Revises: 20260830_0126
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260831_0127"
down_revision = "20260830_0126"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    if op.get_context().as_sql:
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_public_profiles")
    }
    if "popular_search_terms" in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "popular_search_terms",
                JSON_DOCUMENT,
                nullable=True,
            )
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tenant_public_profiles")
    }
    if "popular_search_terms" not in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("popular_search_terms")
