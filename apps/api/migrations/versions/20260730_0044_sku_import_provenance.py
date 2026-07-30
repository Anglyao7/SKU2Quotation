"""Track the latest product-template import for each SKU.

Revision ID: 20260730_0044
Revises: 20260730_0043
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260730_0044"
down_revision = "20260730_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot safely rebuild this heavily referenced table during a
        # migration. Tests and local/demo databases still receive the column
        # and index; production PostgreSQL receives the tenant-scoped FK below.
        op.add_column(
            "skus",
            sa.Column("latest_import_job_id", sa.String(40), nullable=True),
        )
        op.create_index(
            "ix_skus_tenant_latest_import_job",
            "skus",
            ["tenant_id", "latest_import_job_id"],
        )
        return

    with op.batch_alter_table("skus") as batch:
        batch.add_column(
            sa.Column("latest_import_job_id", sa.String(40), nullable=True)
        )
        batch.create_foreign_key(
            "fk_skus_tenant_latest_import_job",
            "import_jobs",
            ["tenant_id", "latest_import_job_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index(
            "ix_skus_tenant_latest_import_job",
            ["tenant_id", "latest_import_job_id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(
            "ix_skus_tenant_latest_import_job",
            table_name="skus",
        )
        op.drop_column("skus", "latest_import_job_id")
        return

    with op.batch_alter_table("skus") as batch:
        batch.drop_index("ix_skus_tenant_latest_import_job")
        batch.drop_constraint(
            "fk_skus_tenant_latest_import_job",
            type_="foreignkey",
        )
        batch.drop_column("latest_import_job_id")
