"""Make knowledge-base ownership tenant-safe for uploaded sources.

Revision ID: 20260815_0084
Revises: 20260815_0083
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260815_0084"
down_revision = "20260815_0083"
branch_labels = None
depends_on = None


COMPOSITE_FK = "fk_support_ai_knowledge_sources_tenant_knowledge_base"
LEGACY_FK = "fk_support_ai_knowledge_sources_knowledge_base"


def upgrade() -> None:
    bind = op.get_bind()
    foreign_keys = sa.inspect(bind).get_foreign_keys("support_ai_knowledge_sources")
    names = {item.get("name") for item in foreign_keys}
    if COMPOSITE_FK in names and LEGACY_FK not in names:
        return
    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        if LEGACY_FK in names:
            batch.drop_constraint(LEGACY_FK, type_="foreignkey")
        if COMPOSITE_FK not in names:
            batch.create_foreign_key(
                COMPOSITE_FK,
                "support_ai_knowledge_bases",
                ["tenant_id", "knowledge_base_id"],
                ["tenant_id", "id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    bind = op.get_bind()
    names = {
        item.get("name")
        for item in sa.inspect(bind).get_foreign_keys("support_ai_knowledge_sources")
    }
    with op.batch_alter_table("support_ai_knowledge_sources") as batch:
        if COMPOSITE_FK in names:
            batch.drop_constraint(COMPOSITE_FK, type_="foreignkey")
        if LEGACY_FK not in names:
            batch.create_foreign_key(
                LEGACY_FK,
                "support_ai_knowledge_bases",
                ["knowledge_base_id"],
                ["id"],
                ondelete="CASCADE",
            )
