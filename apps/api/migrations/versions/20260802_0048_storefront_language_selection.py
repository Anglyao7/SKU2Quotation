"""Add merchant-controlled storefront language selection.

Revision ID: 20260802_0048
Revises: 20260801_0047
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260802_0048"
down_revision = "20260801_0047"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "storefront_locales",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[\"zh-CN\", \"en-US\"]'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("storefront_locales")
