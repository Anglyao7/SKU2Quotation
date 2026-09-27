"""Index normalized and numeric-pattern catalog translation memory.

Existing translations remain untouched.  Their indexes can be populated in
small batches after deployment; this migration does not block on a full-table
data rewrite.

Revision ID: 20260927_0148
Revises: 20260927_0147
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260927_0148"
down_revision = "20260927_0147"
branch_labels = None
depends_on = None


TABLE = "catalog_text_translations"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("normalized_source_hash", sa.String(64)))
    op.add_column(TABLE, sa.Column("numeric_template_hash", sa.String(64)))
    concurrent = op.get_bind().dialect.name == "postgresql"
    if concurrent:
        # A large existing TM must remain writable while indexes are built.
        with op.get_context().autocommit_block():
            _create_indexes(concurrent=True)
    else:
        _create_indexes(concurrent=False)


def _create_indexes(*, concurrent: bool) -> None:
    op.create_index(
        "ix_catalog_text_translations_exact_lookup",
        TABLE,
        ["tenant_id", "source_locale", "target_locale", "source_hash"],
        postgresql_concurrently=concurrent,
    )
    op.create_index(
        "ix_catalog_text_translations_normalized_lookup",
        TABLE,
        ["tenant_id", "source_locale", "target_locale", "normalized_source_hash"],
        postgresql_concurrently=concurrent,
    )
    op.create_index(
        "ix_catalog_text_translations_numeric_lookup",
        TABLE,
        ["tenant_id", "source_locale", "target_locale", "numeric_template_hash"],
        postgresql_concurrently=concurrent,
    )


def downgrade() -> None:
    concurrent = op.get_bind().dialect.name == "postgresql"
    if concurrent:
        with op.get_context().autocommit_block():
            _drop_indexes(concurrent=True)
    else:
        _drop_indexes(concurrent=False)
    op.drop_column(TABLE, "numeric_template_hash")
    op.drop_column(TABLE, "normalized_source_hash")


def _drop_indexes(*, concurrent: bool) -> None:
    op.drop_index(
        "ix_catalog_text_translations_numeric_lookup",
        table_name=TABLE,
        postgresql_concurrently=concurrent,
    )
    op.drop_index(
        "ix_catalog_text_translations_normalized_lookup",
        table_name=TABLE,
        postgresql_concurrently=concurrent,
    )
    op.drop_index(
        "ix_catalog_text_translations_exact_lookup",
        table_name=TABLE,
        postgresql_concurrently=concurrent,
    )
