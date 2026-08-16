"""Add merchant-configurable AI search questions to the public storefront."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260816_0099"
down_revision = "20260816_0098"
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
    if "ai_search_questions" in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "ai_search_questions",
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
    if "ai_search_questions" not in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("ai_search_questions")
