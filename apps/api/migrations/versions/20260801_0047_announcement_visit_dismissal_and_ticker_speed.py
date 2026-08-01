"""Replace announcement repeat intervals with configurable ticker speed.

Revision ID: 20260801_0047
Revises: 20260801_0046
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260801_0047"
down_revision = "20260801_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("storefront_announcements") as batch:
        batch.drop_constraint(
            "ck_storefront_announcements_repeat_interval_hours_valid",
            type_="check",
        )
        batch.drop_column("repeat_interval_hours")
        batch.add_column(
            sa.Column(
                "ticker_speed_px_per_second",
                sa.Integer(),
                nullable=False,
                server_default="60",
            )
        )
        batch.create_check_constraint(
            op.f("ck_storefront_announcements_ticker_speed_px_per_second_valid"),
            "ticker_speed_px_per_second BETWEEN 20 AND 160",
        )


def downgrade() -> None:
    with op.batch_alter_table("storefront_announcements") as batch:
        batch.drop_constraint(
            op.f("ck_storefront_announcements_ticker_speed_px_per_second_valid"),
            type_="check",
        )
        batch.drop_column("ticker_speed_px_per_second")
        batch.add_column(
            sa.Column(
                "repeat_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default="24",
            )
        )
        batch.create_check_constraint(
            "ck_storefront_announcements_repeat_interval_hours_valid",
            "repeat_interval_hours BETWEEN 1 AND 720",
        )
