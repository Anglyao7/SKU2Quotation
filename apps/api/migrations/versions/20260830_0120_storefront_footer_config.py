"""Add merchant-configurable public storefront footer links.

Revision ID: 20260830_0120
Revises: 20260829_0119
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260830_0120"
down_revision = "20260829_0119"
branch_labels = None
depends_on = None


JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(
            sa.Column("storefront_footer_config", JSON_DOCUMENT, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("storefront_footer_config")

