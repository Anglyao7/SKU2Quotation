"""Capture the existing supplier-import MVP schema without deleting user data.

Revision ID: 20260718_0000
Revises: None
"""
from collections.abc import Callable

from alembic import op
import sqlalchemy as sa


revision = "20260718_0000"
down_revision = None
branch_labels = None
depends_on = None


def _create_if_missing(table_name: str, creator: Callable[[], None]) -> None:
    if op.get_context().as_sql or not sa.inspect(op.get_bind()).has_table(table_name):
        creator()


def _create_suppliers() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("active_skus", sa.Integer(), nullable=False),
        sa.Column("health", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_suppliers"),
    )
    op.create_index("ix_suppliers_name", "suppliers", ["name"], unique=True)
    op.create_index("ix_suppliers_status", "suppliers", ["status"])


def _create_source_files() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_filename", sa.String(500), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("detected_type", sa.String(80), nullable=False),
        sa.Column("extension_matches", sa.Boolean(), nullable=False),
        sa.Column("parser", sa.String(80), nullable=False),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source_files"),
    )
    op.create_index("ix_source_files_sha256", "source_files", ["sha256"])


def _create_import_jobs() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("source_file_id", sa.String(40), nullable=False),
        sa.Column("supplier_id", sa.String(40), nullable=True),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("products_count", sa.Integer(), nullable=False),
        sa.Column("warnings_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], name="fk_import_jobs_source_file_id_source_files"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name="fk_import_jobs_supplier_id_suppliers"),
        sa.PrimaryKeyConstraint("id", name="pk_import_jobs"),
    )
    op.create_index("ix_import_jobs_source_file_id", "import_jobs", ["source_file_id"])
    op.create_index("ix_import_jobs_supplier_id", "import_jobs", ["supplier_id"])
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"])
    op.create_index("ix_import_jobs_created_at", "import_jobs", ["created_at"])


def _create_review_items() -> None:
    op.create_table(
        "review_items",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("job_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("model", sa.String(300), nullable=False),
        sa.Column("category", sa.String(300), nullable=False),
        sa.Column("supplier_name", sa.String(200), nullable=False),
        sa.Column("source_filename", sa.String(500), nullable=False),
        sa.Column("source_location", sa.String(300), nullable=False),
        sa.Column("image_status", sa.String(30), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["import_jobs.id"], name="fk_review_items_job_id_import_jobs"),
        sa.PrimaryKeyConstraint("id", name="pk_review_items"),
    )
    op.create_index("ix_review_items_job_id", "review_items", ["job_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])


def upgrade() -> None:
    _create_if_missing("suppliers", _create_suppliers)
    _create_if_missing("source_files", _create_source_files)
    _create_if_missing("import_jobs", _create_import_jobs)
    _create_if_missing("review_items", _create_review_items)


def downgrade() -> None:
    # Deliberately non-destructive: these tables predate Alembic and may contain user imports.
    pass
