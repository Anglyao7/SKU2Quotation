"""Persist the merchant's default storefront language.

Revision ID: 20260815_0085
Revises: 20260815_0084
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260815_0085"
down_revision = "20260815_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("tenant_public_profiles")
    }
    if "storefront_default_locale" in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column(
                "storefront_default_locale",
                sa.String(20),
                nullable=False,
                server_default="zh-CN",
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("tenant_public_profiles")
    }
    if "storefront_default_locale" not in columns:
        return
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("storefront_default_locale")
