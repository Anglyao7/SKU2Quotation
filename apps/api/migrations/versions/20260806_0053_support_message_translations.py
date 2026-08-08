"""Add bidirectional translation metadata to storefront support messages.

Revision ID: 20260806_0053
Revises: 20260803_0052
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260806_0053"
down_revision = "20260803_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("storefront_chat_messages") as batch:
        batch.add_column(sa.Column("draft_body", sa.Text(), nullable=True))
        batch.add_column(sa.Column("translated_body", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("translation_source_locale", sa.String(20), nullable=True)
        )
        batch.add_column(
            sa.Column("translation_target_locale", sa.String(20), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "translation_status",
                sa.String(20),
                nullable=False,
                server_default="PENDING",
            )
        )
        batch.create_check_constraint(
            "ck_storefront_chat_messages_translation_status_allowed",
            "translation_status IN "
            "('PENDING', 'READY', 'FAILED', 'UNAVAILABLE', 'NOT_REQUIRED')",
        )


def downgrade() -> None:
    with op.batch_alter_table("storefront_chat_messages") as batch:
        batch.drop_constraint(
            "ck_storefront_chat_messages_translation_status_allowed",
            type_="check",
        )
        batch.drop_column("translation_status")
        batch.drop_column("translation_target_locale")
        batch.drop_column("translation_source_locale")
        batch.drop_column("translated_body")
        batch.drop_column("draft_body")
