"""Store human-authored knowledge-base training rules."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260815_0090"
down_revision = "20260815_0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        columns = set()
    else:
        columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("support_ai_knowledge_bases")
        }
    if "rules_context" in columns:
        return
    with op.batch_alter_table("support_ai_knowledge_bases") as batch:
        batch.add_column(sa.Column("rules_context", sa.Text(), nullable=True))


def downgrade() -> None:
    if op.get_context().as_sql:
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("support_ai_knowledge_bases")
    }
    if "rules_context" not in columns:
        return
    with op.batch_alter_table("support_ai_knowledge_bases") as batch:
        batch.drop_column("rules_context")
