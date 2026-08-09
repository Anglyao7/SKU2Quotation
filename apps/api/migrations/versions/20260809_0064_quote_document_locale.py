"""Store the storefront locale used to create each public quotation.

Revision ID: 20260809_0064
Revises: 20260809_0063
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0064"
down_revision = "20260809_0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.add_column(
            sa.Column(
                "document_locale",
                sa.String(20),
                nullable=False,
                server_default="zh-CN",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("public_quote_drafts") as batch:
        batch.drop_column("document_locale")
