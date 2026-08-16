"""Add the platform-managed image-to-image provider configuration."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_0093"
down_revision = "20260815_0092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_generation_provider_settings",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=40),
            nullable=False,
            server_default="agnes-ai",
        ),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("model_name", sa.String(length=300), nullable=False),
        sa.Column(
            "timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="180",
        ),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_last_four", sa.String(length=4), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider = 'agnes-ai'", name="provider_supported"),
        sa.CheckConstraint(
            "timeout_seconds >= 60 AND timeout_seconds <= 360",
            name="timeout_supported",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("image_generation_provider_settings")
