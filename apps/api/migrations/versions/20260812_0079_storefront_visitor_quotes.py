"""Bind anonymous storefront visitors to quote status updates.

Revision ID: 20260812_0079
Revises: 20260811_0078
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260812_0079"
down_revision = "20260811_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.drop_constraint(
            "ck_public_quote_drafts_status_allowed",
            type_="check",
        )
        batch.add_column(
            sa.Column("visitor_token_hash", sa.String(64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "visitor_token_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_public_quote_drafts_status_allowed",
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'COMPLETED', "
            "'CANCELLED', 'EXPIRED')",
        )
    op.create_index(
        "ix_public_quote_drafts_tenant_visitor_updated",
        "public_quote_drafts",
        ["tenant_id", "visitor_token_hash", "updated_at"],
    )


def downgrade() -> None:
    # Completed rows cannot satisfy the previous constraint. Keep rollback
    # deterministic by returning them to the last supported confirmed state.
    op.execute(
        "UPDATE public_quote_drafts SET status = 'CONFIRMED' "
        "WHERE status = 'COMPLETED'"
    )
    op.drop_index(
        "ix_public_quote_drafts_tenant_visitor_updated",
        table_name="public_quote_drafts",
    )
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.drop_constraint(
            "ck_public_quote_drafts_status_allowed",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_public_quote_drafts_status_allowed",
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED', 'EXPIRED')",
        )
        batch.drop_column("visitor_token_hash")
        batch.drop_column("visitor_token_expires_at")
