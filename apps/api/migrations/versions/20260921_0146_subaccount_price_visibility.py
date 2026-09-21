"""Add an owner-controlled zero-price policy for child storefronts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260921_0146"
down_revision = "20260920_0145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    columns = {item["name"] for item in sa.inspect(connection).get_columns("subaccount_pricing_policies")}
    if "prices_hidden" not in columns:
        op.add_column(
            "subaccount_pricing_policies",
            sa.Column(
                "prices_hidden",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    connection = op.get_bind()
    columns = {item["name"] for item in sa.inspect(connection).get_columns("subaccount_pricing_policies")}
    if "prices_hidden" in columns:
        op.drop_column("subaccount_pricing_policies", "prices_hidden")
