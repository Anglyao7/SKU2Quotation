"""Add provider RPM and concurrency limits for image-to-image requests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_0096"
down_revision = "20260816_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("image_generation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "requests_per_minute",
                sa.Integer(),
                nullable=False,
                server_default="6",
            )
        )
        batch.add_column(
            sa.Column(
                "concurrency_limit",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch.create_check_constraint(
            "requests_per_minute_supported",
            "requests_per_minute >= 1 AND requests_per_minute <= 10000",
        )
        batch.create_check_constraint(
            "concurrency_supported",
            "concurrency_limit >= 1 AND concurrency_limit <= 32",
        )


def downgrade() -> None:
    with op.batch_alter_table("image_generation_provider_settings") as batch:
        batch.drop_constraint("concurrency_supported", type_="check")
        batch.drop_constraint("requests_per_minute_supported", type_="check")
        batch.drop_column("concurrency_limit")
        batch.drop_column("requests_per_minute")
