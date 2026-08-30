"""Allow platform administrators to request a merchant translation directly.

Revision ID: 20260830_0126
Revises: 20260830_0125
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260830_0126"
down_revision = "20260830_0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.alter_column(
            "requested_by_membership_id",
            existing_type=sa.Uuid(as_uuid=True),
            nullable=True,
        )


def downgrade() -> None:
    # Downgrade requires every platform-initiated job to have been removed or
    # assigned a tenant membership first; existing installations without such
    # rows remain fully reversible.
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.alter_column(
            "requested_by_membership_id",
            existing_type=sa.Uuid(as_uuid=True),
            nullable=False,
        )
