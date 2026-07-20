"""Phase 4A-1B native XLSX/CSV provider registration.

Revision ID: 20260718_0010
Revises: 20260718_0009
Requirements: AIPI-001, AIPI-002, AIPI-009, AIPI-010, PROD-001
"""
from alembic import op


revision = "20260718_0010"
down_revision = "20260718_0009"
branch_labels = None
depends_on = None


def _replace_provider_type_constraint(expression: str) -> None:
    with op.batch_alter_table("ai_runs") as batch_op:
        batch_op.drop_constraint("ck_ai_runs_provider_type_allowed", type_="check")
        batch_op.create_check_constraint(
            "ck_ai_runs_provider_type_allowed",
            expression,
        )


def upgrade() -> None:
    _replace_provider_type_constraint("provider_type IN ('FAKE', 'NATIVE')")


def downgrade() -> None:
    _replace_provider_type_constraint("provider_type IN ('FAKE')")
