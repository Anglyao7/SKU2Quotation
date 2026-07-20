"""Normalize draft-era SQLite tenant UUID text representation.

Revision ID: 20260718_0005
Revises: 20260718_0004
Requirement: MIGDB-003
"""
from alembic import op


revision = "20260718_0005"
down_revision = "20260718_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    bind.exec_driver_sql("PRAGMA defer_foreign_keys=ON")
    for table in ("suppliers", "source_files", "import_jobs", "review_items"):
        op.execute(
            f'UPDATE "{table}" SET tenant_id = REPLACE(tenant_id, \'-\', \'\') '
            "WHERE tenant_id LIKE '%-%'"
        )
    violations = bind.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"SQLite foreign key violations after UUID normalization: {violations!r}")


def downgrade() -> None:
    # Canonical SQLAlchemy UUID text is intentionally not converted back.
    pass
