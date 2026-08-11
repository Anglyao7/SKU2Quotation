"""Add R2 logo references and share-card logo placement.

Revision ID: 20260811_0077
Revises: 20260811_0076
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260811_0077"
down_revision = "20260811_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.add_column(sa.Column("logo_object_key", sa.String(1000), nullable=True))

    with op.batch_alter_table("catalog_shares") as batch:
        batch.add_column(
            sa.Column(
                "logo_position",
                sa.String(20),
                nullable=False,
                server_default="NONE",
            )
        )
        batch.create_check_constraint(
            "ck_catalog_shares_logo_position_allowed",
            "logo_position IN ('NONE', 'TOP_LEFT', 'TOP_RIGHT')",
        )


def downgrade() -> None:
    with op.batch_alter_table("catalog_shares") as batch:
        batch.drop_constraint(
            "ck_catalog_shares_logo_position_allowed",
            type_="check",
        )
        batch.drop_column("logo_position")

    with op.batch_alter_table("tenant_public_profiles") as batch:
        batch.drop_column("logo_object_key")
