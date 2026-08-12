"""Track actionable storefront human-support requests.

Revision ID: 20260813_0082
Revises: 20260812_0080
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260813_0082"
down_revision = "20260812_0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "storefront_chat_conversations",
        sa.Column(
            "human_handoff_offered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "storefront_chat_conversations",
        sa.Column(
            "human_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "storefront_chat_conversations",
        sa.Column(
            "human_resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "storefront_chat_conversations",
        sa.Column("human_request_reason", sa.String(80), nullable=True),
    )
    op.create_index(
        "ix_storefront_chat_conversations_tenant_human_request",
        "storefront_chat_conversations",
        ["tenant_id", "human_requested_at", "human_resolved_at", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_storefront_chat_conversations_tenant_human_request",
        table_name="storefront_chat_conversations",
    )
    op.drop_column("storefront_chat_conversations", "human_request_reason")
    op.drop_column("storefront_chat_conversations", "human_resolved_at")
    op.drop_column("storefront_chat_conversations", "human_requested_at")
    op.drop_column("storefront_chat_conversations", "human_handoff_offered_at")
