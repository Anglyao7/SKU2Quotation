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
    existing_columns = {
        column["name"]
        for column in sa.inspect(connection).get_columns("tenants")
    }
    # A previous local startup may have applied SQLite's direct ADD COLUMN
    # before the migration version row was committed. Treat that state as an
    # interrupted migration and continue without adding the column twice.
    if "dashboard_timezones" in existing_columns:
        return
    serialized_default = json.dumps(DEFAULT_TIMEZONES, ensure_ascii=False)
    escaped_default = serialized_default.replace("'", "''")
    if connection.dialect.name == "sqlite":
        # Rebuilding tenants through batch mode invalidates existing SQLite
        # triggers that reference the table. SQLite can add this non-null
        # column directly when a constant default is supplied.
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

    # PostgreSQL must receive a non-null constant at ADD COLUMN time. An
    # UPDATE followed by a separate ALTER can still leave legacy rows null
    # when the column's JSON value is adapted by the driver, causing the
    # constraint step to fail during a live deployment.
    op.add_column(
        "tenants",
        sa.Column(
            "dashboard_timezones",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(f"'{escaped_default}'::json"),
        ),
    )
    op.alter_column(
        "tenants",
        "dashboard_timezones",
        existing_type=sa.JSON(),
        server_default=None,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_column("tenants", "dashboard_timezones")
        return
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("dashboard_timezones")
