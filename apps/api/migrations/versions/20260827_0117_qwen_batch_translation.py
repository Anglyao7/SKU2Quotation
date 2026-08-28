"""Add resumable Qwen Batch catalog translation.

Revision ID: 20260827_0117
Revises: 20260827_0116
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260827_0117"
down_revision = "20260827_0116"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)
DEFAULT_BATCH_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_BATCH_MODEL = "qwen3.7-flash-2026-07-15"


def upgrade() -> None:
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.add_column(
            sa.Column(
                "catalog_execution_mode",
                sa.String(length=30),
                nullable=False,
                server_default="REALTIME",
            )
        )
        batch.add_column(
            sa.Column(
                "batch_base_url",
                sa.String(length=1000),
                nullable=False,
                server_default=DEFAULT_BATCH_BASE_URL,
            )
        )
        batch.add_column(
            sa.Column(
                "batch_model_name",
                sa.String(length=300),
                nullable=False,
                server_default=DEFAULT_BATCH_MODEL,
            )
        )
        batch.add_column(
            sa.Column("batch_api_key_ciphertext", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "batch_api_key_last_four",
                sa.String(length=4),
                nullable=True,
            )
        )

    # The requested Batch profile starts with the already encrypted Qwen
    # compatible credential.  No plaintext secret is exposed during migration.
    op.execute(
        sa.text(
            "UPDATE translation_provider_settings "
            "SET catalog_execution_mode = 'QWEN_BATCH', "
            "batch_base_url = base_url, "
            "batch_api_key_ciphertext = api_key_ciphertext, "
            "batch_api_key_last_four = api_key_last_four "
            "WHERE id = 'CATALOG_TRANSLATION' "
            "AND provider = 'openai-compatible' "
            "AND lower(base_url) LIKE '%dashscope%aliyuncs.com%' "
            "AND api_key_ciphertext IS NOT NULL"
        )
    )
    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.create_check_constraint(
            "ck_translation_provider_settings_catalog_execution_mode_supported",
            "catalog_execution_mode IN ('REALTIME', 'QWEN_BATCH')",
        )
        batch.create_check_constraint(
            "ck_translation_provider_settings_batch_key_required",
            "catalog_execution_mode = 'REALTIME' OR "
            "batch_api_key_ciphertext IS NOT NULL",
        )

    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.add_column(
            sa.Column(
                "execution_mode",
                sa.String(length=30),
                nullable=False,
                server_default="REALTIME",
            )
        )
        batch.add_column(
            sa.Column(
                "batch_request_payload",
                JSON_DOCUMENT,
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column("external_input_file_id", sa.String(length=200), nullable=True)
        )
        batch.add_column(
            sa.Column("external_batch_id", sa.String(length=200), nullable=True)
        )
        batch.add_column(
            sa.Column("external_output_file_id", sa.String(length=200), nullable=True)
        )
        batch.add_column(
            sa.Column("external_error_file_id", sa.String(length=200), nullable=True)
        )
        batch.add_column(
            sa.Column("external_batch_status", sa.String(length=40), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "external_total_requests",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "external_completed_requests",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "external_failed_requests",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_execution_mode_allowed",
            "execution_mode IN ('REALTIME', 'QWEN_BATCH')",
        )
        batch.create_check_constraint(
            "ck_catalog_translation_jobs_external_request_counts_nonnegative",
            "external_total_requests >= 0 AND "
            "external_completed_requests >= 0 AND "
            "external_failed_requests >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("catalog_translation_jobs") as batch:
        batch.drop_constraint(
            "ck_catalog_translation_jobs_external_request_counts_nonnegative",
            type_="check",
        )
        batch.drop_constraint(
            "ck_catalog_translation_jobs_execution_mode_allowed",
            type_="check",
        )
        batch.drop_column("external_failed_requests")
        batch.drop_column("external_completed_requests")
        batch.drop_column("external_total_requests")
        batch.drop_column("external_batch_status")
        batch.drop_column("external_error_file_id")
        batch.drop_column("external_output_file_id")
        batch.drop_column("external_batch_id")
        batch.drop_column("external_input_file_id")
        batch.drop_column("batch_request_payload")
        batch.drop_column("execution_mode")

    with op.batch_alter_table("translation_provider_settings") as batch:
        batch.drop_constraint(
            "ck_translation_provider_settings_batch_key_required",
            type_="check",
        )
        batch.drop_constraint(
            "ck_translation_provider_settings_catalog_execution_mode_supported",
            type_="check",
        )
        batch.drop_column("batch_api_key_last_four")
        batch.drop_column("batch_api_key_ciphertext")
        batch.drop_column("batch_model_name")
        batch.drop_column("batch_base_url")
        batch.drop_column("catalog_execution_mode")
