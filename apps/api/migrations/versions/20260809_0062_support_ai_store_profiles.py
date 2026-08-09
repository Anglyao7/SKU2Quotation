"""Scope customer-service AI to stores and add reusable provider profiles.

Revision ID: 20260809_0062
Revises: 20260809_0061
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260809_0062"
down_revision = "20260809_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("support_ai_provider_settings") as batch:
        batch.add_column(sa.Column("configuration_name", sa.String(160), nullable=True))
        batch.add_column(sa.Column("display_model_name", sa.String(160), nullable=True))
        batch.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_support_ai_provider_settings_created_by_user",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        sa.text(
            """
            UPDATE support_ai_provider_settings
            SET configuration_name = CASE
                    WHEN id = 'SUPPORT_AI_GENERATION' THEN '平台默认 API'
                    ELSE 'API 配置 ' || id
                END,
                display_model_name = model_name,
                created_by_user_id = updated_by_user_id
            WHERE configuration_name IS NULL OR display_model_name IS NULL
            """
        )
    )

    with op.batch_alter_table("support_ai_provider_settings") as batch:
        batch.alter_column(
            "configuration_name",
            existing_type=sa.String(160),
            nullable=False,
        )
        batch.alter_column(
            "display_model_name",
            existing_type=sa.String(160),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_support_ai_provider_configuration_name",
            ["configuration_name"],
        )

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.add_column(
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("provider_setting_id", sa.String(40), nullable=True)
        )
        batch.create_foreign_key(
            "fk_support_ai_settings_provider_setting",
            "support_ai_provider_settings",
            ["provider_setting_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        sa.text(
            """
            UPDATE support_ai_settings
            SET enabled = CASE
                    WHEN mode IN ('AUTO_LIMITED', 'AUTO') THEN TRUE
                    ELSE FALSE
                END,
                provider_setting_id = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM support_ai_provider_settings
                        WHERE id = 'SUPPORT_AI_GENERATION'
                    ) THEN 'SUPPORT_AI_GENERATION'
                    ELSE NULL
                END
            """
        )
    )

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.drop_constraint(
            "ck_support_ai_settings_mode_allowed", type_="check"
        )
        batch.drop_column("mode")

    with op.batch_alter_table("support_ai_runs") as batch:
        batch.add_column(
            sa.Column(
                "enabled_snapshot",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("provider_setting_id", sa.String(40), nullable=True)
        )
        batch.add_column(
            sa.Column("model_display_name", sa.String(160), nullable=True)
        )
        batch.create_foreign_key(
            "fk_support_ai_runs_provider_setting",
            "support_ai_provider_settings",
            ["provider_setting_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.execute(
        sa.text(
            """
            UPDATE support_ai_runs
            SET enabled_snapshot = CASE
                    WHEN mode_snapshot IN ('AUTO_LIMITED', 'AUTO') THEN TRUE
                    ELSE FALSE
                END,
                provider_setting_id = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM support_ai_provider_settings
                        WHERE id = 'SUPPORT_AI_GENERATION'
                    ) THEN 'SUPPORT_AI_GENERATION'
                    ELSE NULL
                END,
                model_display_name = COALESCE(
                    (
                        SELECT display_model_name
                        FROM support_ai_provider_settings
                        WHERE id = 'SUPPORT_AI_GENERATION'
                    ),
                    model_name
                )
            """
        )
    )

    with op.batch_alter_table("support_ai_runs") as batch:
        batch.drop_constraint(
            "ck_support_ai_runs_mode_snapshot_allowed", type_="check"
        )
        batch.drop_column("mode_snapshot")


def downgrade() -> None:
    with op.batch_alter_table("support_ai_runs") as batch:
        batch.add_column(
            sa.Column(
                "mode_snapshot",
                sa.String(30),
                nullable=False,
                server_default="OFF",
            )
        )

    op.execute(
        sa.text(
            """
            UPDATE support_ai_runs
            SET mode_snapshot = CASE
                    WHEN enabled_snapshot THEN 'AUTO_LIMITED'
                    ELSE 'OFF'
                END
            """
        )
    )

    with op.batch_alter_table("support_ai_runs") as batch:
        batch.create_check_constraint(
            "ck_support_ai_runs_mode_snapshot_allowed",
            "mode_snapshot IN ('OFF', 'DRAFT', 'SHADOW', 'AUTO_LIMITED', 'AUTO')",
        )
        batch.drop_constraint(
            "fk_support_ai_runs_provider_setting", type_="foreignkey"
        )
        batch.drop_column("model_display_name")
        batch.drop_column("provider_setting_id")
        batch.drop_column("enabled_snapshot")

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.String(30),
                nullable=False,
                server_default="OFF",
            )
        )

    op.execute(
        sa.text(
            """
            UPDATE support_ai_settings
            SET mode = CASE
                    WHEN enabled THEN 'AUTO_LIMITED'
                    ELSE 'OFF'
                END
            """
        )
    )

    with op.batch_alter_table("support_ai_settings") as batch:
        batch.create_check_constraint(
            "ck_support_ai_settings_mode_allowed",
            "mode IN ('OFF', 'DRAFT', 'SHADOW', 'AUTO_LIMITED', 'AUTO')",
        )
        batch.drop_constraint(
            "fk_support_ai_settings_provider_setting", type_="foreignkey"
        )
        batch.drop_column("provider_setting_id")
        batch.drop_column("enabled")

    with op.batch_alter_table("support_ai_provider_settings") as batch:
        batch.drop_constraint(
            "uq_support_ai_provider_configuration_name", type_="unique"
        )
        batch.drop_constraint(
            "fk_support_ai_provider_settings_created_by_user", type_="foreignkey"
        )
        batch.drop_column("created_by_user_id")
        batch.drop_column("display_model_name")
        batch.drop_column("configuration_name")
