"""Persist the dashboard's visible world-time locations per merchant."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260916_0143"
down_revision = "20260913_0142"
branch_labels = None
depends_on = None


DEFAULT_TIMEZONES = [
    "china",
    "united_states",
    "spain",
    "turkey",
    "arab_region",
    "united_arab_emirates",
    "united_kingdom",
    "japan",
    "south_korea",
]


def upgrade() -> None:
    connection = op.get_bind()
    serialized_default = json.dumps(DEFAULT_TIMEZONES, ensure_ascii=False)
    if connection.dialect.name == "sqlite":
        # Rebuilding tenants through batch mode invalidates existing SQLite
        # triggers that reference the table. SQLite can add this non-null
        # column directly when a constant default is supplied.
        escaped_default = serialized_default.replace("'", "''")
        op.add_column(
            "tenants",
            sa.Column(
                "dashboard_timezones",
                sa.JSON(),
                nullable=False,
                server_default=sa.text(f"'{escaped_default}'"),
            ),
        )
        return
    op.add_column(
        "tenants",
        sa.Column("dashboard_timezones", sa.JSON(), nullable=True),
    )
    connection.execute(
        sa.text(
            "UPDATE tenants SET dashboard_timezones = :value "
            "WHERE dashboard_timezones IS NULL"
        ),
        {"value": serialized_default},
    )
    with op.batch_alter_table("tenants") as batch:
        batch.alter_column("dashboard_timezones", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_column("tenants", "dashboard_timezones")
        return
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("dashboard_timezones")
