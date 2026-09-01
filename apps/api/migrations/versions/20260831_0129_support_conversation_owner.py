"""Scope storefront support conversations to the owning account.

Revision ID: 20260831_0129
Revises: 20260831_0128
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_0129"
down_revision = "20260831_0128"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "storefront_chat_conversations"
        )
    }


def upgrade() -> None:
    if op.get_context().as_sql or "owner_membership_id" in _columns():
        return
    with op.batch_alter_table("storefront_chat_conversations") as batch:
        batch.add_column(sa.Column("owner_membership_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_storefront_chat_conversations_owner_membership",
            "memberships",
            ["tenant_id", "owner_membership_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_storefront_chat_conversations_tenant_owner_activity",
            ["tenant_id", "owner_membership_id", "status", "last_message_at"],
            unique=False,
        )


def downgrade() -> None:
    if op.get_context().as_sql or "owner_membership_id" not in _columns():
        return
    with op.batch_alter_table("storefront_chat_conversations") as batch:
        batch.drop_index(
            "ix_storefront_chat_conversations_tenant_owner_activity"
        )
        batch.drop_constraint(
            "fk_storefront_chat_conversations_owner_membership",
            type_="foreignkey",
        )
        batch.drop_column("owner_membership_id")
