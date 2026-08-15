"""Ensure every quote workspace has a persistent quotation number.

The first workspace migration was already applied in some local databases
before the quotation-number column was present.  This follow-up is
intentionally additive and idempotent so both those databases and clean
installs converge on the same schema.

Revision ID: 20260815_0092
Revises: 20260815_0091
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260815_0092"
down_revision = "20260815_0091"
branch_labels = None
depends_on = None


def _columns(bind) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(bind).get_columns("public_quote_drafts")
    }


def upgrade() -> None:
    bind = op.get_bind()
    if op.get_context().as_sql:
        return
    columns = _columns(bind)
    if "quotation_number" not in columns:
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.add_column(sa.Column("quotation_number", sa.String(80), nullable=True))

    # A unique index is portable across SQLite and PostgreSQL and, like the
    # original constraint, permits multiple drafts without a number while
    # preventing duplicate formal numbers within one merchant.
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_public_quote_drafts_tenant_quotation_number "
            "ON public_quote_drafts (tenant_id, quotation_number)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if op.get_context().as_sql:
        return
    bind.execute(
        sa.text(
            "DROP INDEX IF EXISTS uq_public_quote_drafts_tenant_quotation_number"
        )
    )
    if "quotation_number" in _columns(bind):
        with op.batch_alter_table("public_quote_drafts") as batch:
            batch.drop_column("quotation_number")
