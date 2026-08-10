"""Add approved public company context for support AI social replies.

Revision ID: 20260810_0070
Revises: 20260809_0069
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260810_0070"
down_revision = "20260809_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("support_ai_agents") as batch:
        batch.add_column(
            sa.Column("public_company_introduction", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("public_service_scope", sa.Text(), nullable=True)
        )
    with op.batch_alter_table("support_ai_settings") as batch:
        batch.add_column(
            sa.Column("public_company_introduction", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("public_service_scope", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("support_ai_settings") as batch:
        batch.drop_column("public_service_scope")
        batch.drop_column("public_company_introduction")
    with op.batch_alter_table("support_ai_agents") as batch:
        batch.drop_column("public_service_scope")
        batch.drop_column("public_company_introduction")
