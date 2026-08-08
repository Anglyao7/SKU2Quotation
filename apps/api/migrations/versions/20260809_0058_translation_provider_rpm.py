"""Add platform-managed translation requests-per-minute limit.

Revision ID: 20260809_0058
Revises: 20260808_0057
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0058"
down_revision = "20260808_0057"
branch_labels = None
depends_on = None


RPM_CONSTRAINT = (
    "ck_translation_provider_settings_requests_per_minute_supported"
)


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "requests_per_minute",
                sa.Integer(),
                nullable=False,
                server_default="60",
            )
        )
        batch.create_check_constraint(
            RPM_CONSTRAINT,
            "requests_per_minute >= 1 AND requests_per_minute <= 10000",
        )


def downgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(RPM_CONSTRAINT, type_="check")
        batch.drop_column("requests_per_minute")
