"""Separate safe rollback ownership from latest import provenance.

Revision ID: 20260812_0081
Revises: 20260812_0080
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260812_0081"
down_revision = "20260812_0080"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # As with migration 0044, avoid rebuilding the heavily referenced SKU
        # table in local/demo SQLite databases. Production PostgreSQL receives
        # the tenant-scoped foreign key below.
        op.add_column(
            "skus",
            sa.Column("rollback_owner_batch_id", U(), nullable=True),
        )
        op.create_index(
            "ix_skus_tenant_rollback_owner_batch",
            "skus",
            ["tenant_id", "rollback_owner_batch_id"],
        )
        return

    with op.batch_alter_table("skus") as batch:
        batch.add_column(
            sa.Column("rollback_owner_batch_id", U(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_skus_tenant_rollback_owner_batch",
            "catalog_import_batches",
            ["tenant_id", "rollback_owner_batch_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_skus_tenant_rollback_owner_batch",
            ["tenant_id", "rollback_owner_batch_id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(
            "ix_skus_tenant_rollback_owner_batch",
            table_name="skus",
        )
        op.drop_column("skus", "rollback_owner_batch_id")
        return

    with op.batch_alter_table("skus") as batch:
        batch.drop_index("ix_skus_tenant_rollback_owner_batch")
        batch.drop_constraint(
            "fk_skus_tenant_rollback_owner_batch",
            type_="foreignkey",
        )
        batch.drop_column("rollback_owner_batch_id")
