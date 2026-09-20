"""Store the storefront search-query translation settings in the config center."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260920_0145"
down_revision = "20260917_0144"
branch_labels = None
depends_on = None


TABLE = "translation_provider_settings"


def _add_column(connection, name: str, column: sa.Column) -> None:
    existing = {item["name"] for item in sa.inspect(connection).get_columns(TABLE)}
    if name not in existing:
        op.add_column(TABLE, column)


def upgrade() -> None:
    connection = op.get_bind()
    _add_column(
        connection,
        "search_translation_enabled",
        sa.Column(
            "search_translation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    _add_column(
        connection,
        "search_translation_endpoint",
        sa.Column(
            "search_translation_endpoint",
            sa.String(1000),
            nullable=False,
            server_default=sa.text(
                "'https://fanyi-api.baidu.com/ait/api/aiTextTranslate'"
            ),
        ),
    )
    _add_column(
        connection,
        "search_translation_timeout_seconds",
        sa.Column(
            "search_translation_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("8"),
        ),
    )
    _add_column(
        connection,
        "search_translation_cache_ttl_seconds",
        sa.Column(
            "search_translation_cache_ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("86400"),
        ),
    )
    _add_column(
        connection,
        "search_translation_api_key_ciphertext",
        sa.Column("search_translation_api_key_ciphertext", sa.Text(), nullable=True),
    )
    _add_column(
        connection,
        "search_translation_api_key_last_four",
        sa.Column("search_translation_api_key_last_four", sa.String(4), nullable=True),
    )
    _add_column(
        connection,
        "search_translation_app_id_ciphertext",
        sa.Column("search_translation_app_id_ciphertext", sa.Text(), nullable=True),
    )
    _add_column(
        connection,
        "search_translation_app_id_last_four",
        sa.Column("search_translation_app_id_last_four", sa.String(4), nullable=True),
    )


def downgrade() -> None:
    connection = op.get_bind()
    existing = {item["name"] for item in sa.inspect(connection).get_columns(TABLE)}
    for name in (
        "search_translation_app_id_last_four",
        "search_translation_app_id_ciphertext",
        "search_translation_api_key_last_four",
        "search_translation_api_key_ciphertext",
        "search_translation_cache_ttl_seconds",
        "search_translation_timeout_seconds",
        "search_translation_endpoint",
        "search_translation_enabled",
    ):
        if name in existing:
            op.drop_column(TABLE, name)
