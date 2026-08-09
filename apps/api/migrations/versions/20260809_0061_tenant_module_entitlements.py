"""Add platform-managed visible modules for every merchant.

Revision ID: 20260809_0061
Revises: 20260809_0060
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260809_0061"
down_revision = "20260809_0060"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)

DEFAULT_MODULES = [
    "products",
    "analytics",
    "inventory",
    "announcements",
    "support",
    "support_ai",
    "inquiries",
    "quotations",
    "subaccounts",
    "team",
]


def upgrade() -> None:
    serialized_default = json.dumps(DEFAULT_MODULES, separators=(",", ":"))
    default_sql = (
        f"'{serialized_default}'::jsonb"
        if op.get_bind().dialect.name == "postgresql"
        else f"'{serialized_default}'"
    )
    op.add_column(
        "tenants",
        sa.Column(
            "enabled_modules",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text(default_sql),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "enabled_modules")
