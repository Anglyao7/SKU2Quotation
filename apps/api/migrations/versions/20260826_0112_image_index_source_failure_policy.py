"""Add source failure policies and skipped checkpoints to image index jobs.

Revision ID: 20260826_0112
Revises: 20260826_0111
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260826_0112"
down_revision = "20260826_0111"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("image_index_jobs") as batch:
        batch.add_column(
            sa.Column(
                "skipped_images",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "skipped_image_ids",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "skipped_image_failures",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "source_failure_policy",
                sa.String(30),
                nullable=False,
                server_default="STOP",
            )
        )
        batch.create_check_constraint(
            "ck_image_index_jobs_skipped_images_nonnegative",
            "skipped_images >= 0",
        )
        batch.create_check_constraint(
            "ck_image_index_jobs_source_failure_policy_allowed",
            "source_failure_policy IN "
            "('STOP', 'SKIP_NOT_FOUND', 'SKIP_UNREADABLE')",
        )


def downgrade() -> None:
    with op.batch_alter_table("image_index_jobs") as batch:
        batch.drop_constraint(
            "ck_image_index_jobs_source_failure_policy_allowed",
            type_="check",
        )
        batch.drop_constraint(
            "ck_image_index_jobs_skipped_images_nonnegative",
            type_="check",
        )
        batch.drop_column("source_failure_policy")
        batch.drop_column("skipped_image_failures")
        batch.drop_column("skipped_image_ids")
        batch.drop_column("skipped_images")
