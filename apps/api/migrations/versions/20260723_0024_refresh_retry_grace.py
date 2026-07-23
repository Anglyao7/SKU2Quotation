"""Add bounded idempotency metadata for rotating refresh tokens.

Revision ID: 20260723_0024
Revises: 20260723_0023
"""

import sqlalchemy as sa
from alembic import op


revision = "20260723_0024"
down_revision = "20260723_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("auth_refresh_tokens") as batch:
        batch.add_column(
            sa.Column("rotation_request_hash", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "retry_grace_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_auth_refresh_tokens_retry_metadata_pair",
            "(rotation_request_hash IS NULL AND retry_grace_expires_at IS NULL) "
            "OR (rotation_request_hash IS NOT NULL AND retry_grace_expires_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("auth_refresh_tokens") as batch:
        batch.drop_constraint(
            "ck_auth_refresh_tokens_retry_metadata_pair",
            type_="check",
        )
        batch.drop_column("retry_grace_expires_at")
        batch.drop_column("rotation_request_hash")
