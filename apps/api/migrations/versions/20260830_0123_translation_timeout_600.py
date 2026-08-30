"""Raise the catalog translation request timeout limit to 600 seconds.

Revision ID: 20260830_0123
Revises: 20260830_0122
"""

from __future__ import annotations

from alembic import op


revision = "20260830_0123"
down_revision = "20260830_0122"
branch_labels = None
depends_on = None

_TABLE = "translation_provider_settings"
_CONSTRAINT = "ck_translation_provider_settings_timeout_supported"


def _replace_timeout_constraint(maximum: int) -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(
            _CONSTRAINT,
            f"timeout_seconds >= 1 AND timeout_seconds <= {maximum}",
        )


def upgrade() -> None:
    _replace_timeout_constraint(600)


def downgrade() -> None:
    # A value saved after this migration would violate the restored check.
    # Clamp it first so an emergency rollback remains executable.
    op.execute(
        "UPDATE translation_provider_settings "
        "SET timeout_seconds = 120 WHERE timeout_seconds > 120"
    )
    _replace_timeout_constraint(120)
