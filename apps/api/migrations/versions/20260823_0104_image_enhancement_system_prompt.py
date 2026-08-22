"""Add the platform-managed image enhancement system prompt."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260823_0104"
down_revision = "20260822_0103"
branch_labels = None
depends_on = None

DEFAULT_SYSTEM_PROMPT = (
    "Enhance only the provided product image: make it sharper, clearer, and less noisy. "
    "The input image is the source of truth. Preserve the exact product, colors, materials, "
    "shape, proportions, existing text, markings, existing logos, background, lighting, and composition. "
    "Do not add, remove, redraw, or invent any logo, text, label, accessory, decoration, prop, or other object. "
    "Do not change the background or create a new design."
)


def upgrade() -> None:
    with op.batch_alter_table("image_generation_provider_settings") as batch:
        batch.add_column(sa.Column("system_prompt", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE image_generation_provider_settings "
            "SET system_prompt = :prompt "
            "WHERE system_prompt IS NULL"
        ).bindparams(prompt=DEFAULT_SYSTEM_PROMPT)
    )
    with op.batch_alter_table("image_generation_provider_settings") as batch:
        batch.alter_column(
            "system_prompt",
            existing_type=sa.Text(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("image_generation_provider_settings") as batch:
        batch.drop_column("system_prompt")
