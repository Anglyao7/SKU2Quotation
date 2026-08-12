"""Add traceable product import batches and batch rollback ownership.

Revision ID: 20260812_0080
Revises: 20260812_0079
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260812_0080"
down_revision = "20260812_0079"
branch_labels = None
depends_on = None

U = lambda: sa.Uuid(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    offline = op.get_context().as_sql
    inspector = None if offline else sa.inspect(bind)
    if inspector is None or not inspector.has_table("catalog_import_batches"):
        op.create_table(
            "catalog_import_batches",
            sa.Column("id", U(), nullable=False),
            sa.Column("tenant_id", U(), nullable=False),
            sa.Column("created_by_membership_id", U(), nullable=False),
            sa.Column("created_by_user_id", U(), nullable=False),
            sa.Column(
                "expected_file_count", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column(
                "status", sa.String(30), nullable=False, server_default="ACTIVE"
            ),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'PARTIALLY_REVOKED', 'REVOKED')",
                name="ck_catalog_import_batches_status_allowed",
            ),
            sa.CheckConstraint(
                "expected_file_count > 0 AND expected_file_count <= 100",
                name="ck_catalog_import_batches_expected_file_count_valid",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id"],
                ["tenants.id"],
                name="fk_catalog_import_batches_tenant_id_tenants",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "created_by_membership_id"],
                ["memberships.tenant_id", "memberships.id"],
                name="fk_catalog_import_batches_tenant_creator",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                name="fk_catalog_import_batches_created_by_user_id_users",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_catalog_import_batches"),
            sa.UniqueConstraint(
                "tenant_id",
                "id",
                name="uq_catalog_import_batches_tenant_identity",
            ),
        )
        if not offline:
            inspector = sa.inspect(bind)
    batch_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes("catalog_import_batches")
        }
        if inspector is not None
        else set()
    )
    if "ix_catalog_import_batches_tenant_created" not in batch_indexes:
        op.create_index(
            "ix_catalog_import_batches_tenant_created",
            "catalog_import_batches",
            ["tenant_id", "created_at"],
        )

    import_job_columns = (
        {column["name"] for column in inspector.get_columns("import_jobs")}
        if inspector is not None
        else set()
    )
    if "batch_id" not in import_job_columns:
        if bind.dialect.name == "sqlite":
            # SQLite must rebuild a table to add a composite foreign key. Its
            # child tables make that rebuild fail while FK enforcement is on,
            # so suspend enforcement only for this Alembic-owned operation.
            bind.commit()
            bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
            try:
                # A stopped local migration may leave this empty transient
                # table behind. It is never application data.
                inspector = sa.inspect(bind)
                if inspector.has_table("_alembic_tmp_import_jobs"):
                    op.drop_table("_alembic_tmp_import_jobs")
                with op.batch_alter_table("import_jobs") as batch:
                    batch.add_column(sa.Column("batch_id", U(), nullable=True))
                    batch.create_foreign_key(
                        "fk_import_jobs_tenant_batch",
                        "catalog_import_batches",
                        ["tenant_id", "batch_id"],
                        ["tenant_id", "id"],
                        ondelete="RESTRICT",
                    )
                    batch.create_index(
                        "ix_import_jobs_tenant_batch",
                        ["tenant_id", "batch_id"],
                    )
            finally:
                bind.commit()
                bind.exec_driver_sql("PRAGMA foreign_keys=ON")
        else:
            with op.batch_alter_table("import_jobs") as batch:
                batch.add_column(sa.Column("batch_id", U(), nullable=True))
                batch.create_foreign_key(
                    "fk_import_jobs_tenant_batch",
                    "catalog_import_batches",
                    ["tenant_id", "batch_id"],
                    ["tenant_id", "id"],
                    ondelete="RESTRICT",
                )
                batch.create_index(
                    "ix_import_jobs_tenant_batch",
                    ["tenant_id", "batch_id"],
                )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "catalog_import_batches" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "catalog_import_batches" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "catalog_import_batches_tenant_isolation" '
            'ON "catalog_import_batches" FOR ALL '
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        inspector = sa.inspect(bind)
        import_job_indexes = {
            index["name"] for index in inspector.get_indexes("import_jobs")
        }
        import_job_foreign_keys = {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys("import_jobs")
        }
        import_job_columns = {
            column["name"] for column in inspector.get_columns("import_jobs")
        }
        bind.commit()
        bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            with op.batch_alter_table("import_jobs") as batch:
                if "ix_import_jobs_tenant_batch" in import_job_indexes:
                    batch.drop_index("ix_import_jobs_tenant_batch")
                if "fk_import_jobs_tenant_batch" in import_job_foreign_keys:
                    batch.drop_constraint(
                        "fk_import_jobs_tenant_batch", type_="foreignkey"
                    )
                if "batch_id" in import_job_columns:
                    batch.drop_column("batch_id")
        finally:
            bind.commit()
            bind.exec_driver_sql("PRAGMA foreign_keys=ON")
    else:
        with op.batch_alter_table("import_jobs") as batch:
            batch.drop_index("ix_import_jobs_tenant_batch")
            batch.drop_constraint("fk_import_jobs_tenant_batch", type_="foreignkey")
            batch.drop_column("batch_id")
    op.drop_index(
        "ix_catalog_import_batches_tenant_created",
        table_name="catalog_import_batches",
    )
    op.drop_table("catalog_import_batches")
