"""Add object metadata, quarantine security state and durable file worker jobs.

Revision ID: 20260718_0013
Revises: 20260718_0012
Requirements: PROD-001, PROD-002, API-006, API-007, SEC-003,
DB-FILE-001, DB-JOB-001, ACG-007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0013"
down_revision = "20260718_0012"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "media_objects",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("zone", sa.String(30), nullable=False, server_default="QUARANTINE"),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("declared_media_type", sa.String(200), nullable=True),
        sa.Column("detected_media_type", sa.String(200), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUARANTINED"),
        sa.Column("scan_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("scan_engine", sa.String(100), nullable=True),
        sa.Column("scan_result", JSON_DOCUMENT, nullable=False),
        sa.Column("scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_media_id", _uuid(), nullable=True),
        sa.Column("retention_class", sa.String(40), nullable=False, server_default="SOURCE_DEFAULT"),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", _uuid(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("byte_size >= 0", name="ck_media_objects_byte_size_nonnegative"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_media_objects_sha256_length"),
        sa.CheckConstraint(
            "zone IN ('QUARANTINE', 'SOURCE', 'DERIVED', 'APPROVED_MEDIA', "
            "'DOCUMENT', 'LEGAL_HOLD')",
            name="ck_media_objects_zone_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADING', 'QUARANTINED', 'SCANNING', 'AVAILABLE', "
            "'REJECTED', 'DELETED')",
            name="ck_media_objects_status_allowed",
        ),
        sa.CheckConstraint(
            "scan_status IN ('PENDING', 'RUNNING', 'CLEAN', 'INFECTED', 'ERROR')",
            name="ck_media_objects_scan_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_media_objects_tenant_id_tenants", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name="fk_media_objects_created_by_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_media_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_media_objects_tenant_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_objects"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_media_objects_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_media_objects_tenant_object_key"),
    )
    op.create_index("ix_media_objects_tenant_sha256", "media_objects", ["tenant_id", "sha256"])
    op.create_index(
        "ix_media_objects_tenant_scan_status",
        "media_objects",
        ["tenant_id", "scan_status", "status"],
    )

    with op.batch_alter_table("source_files") as batch_op:
        batch_op.add_column(sa.Column("media_object_id", _uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "security_status",
                sa.String(30),
                nullable=False,
                server_default="LEGACY_ACCEPTED",
            )
        )
        batch_op.create_foreign_key(
            "fk_source_files_tenant_media",
            "media_objects",
            ["tenant_id", "media_object_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "security_status_allowed",
            "security_status IN ('PENDING_SCAN', 'SCANNING', 'ACCEPTED', "
            "'QUARANTINED', 'REJECTED', 'SCAN_ERROR', 'LEGACY_ACCEPTED')",
        )

    op.create_table(
        "worker_jobs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("job_type", sa.String(60), nullable=False, server_default="FILE_SCAN_AND_PARSE"),
        sa.Column("media_object_id", _uuid(), nullable=False),
        sa.Column("source_file_id", sa.String(40), nullable=False),
        sa.Column("import_job_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", JSON_DOCUMENT, nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("attempt_count >= 0", name="ck_worker_jobs_attempt_count_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_worker_jobs_max_attempts_positive"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'RETRY', 'SUCCEEDED', 'FAILED', 'DEAD')",
            name="ck_worker_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "job_type IN ('FILE_SCAN_AND_PARSE')", name="ck_worker_jobs_job_type_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_worker_jobs_tenant_id_tenants", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "media_object_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_worker_jobs_tenant_media",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_file_id"],
            ["source_files.tenant_id", "source_files.id"],
            name="fk_worker_jobs_tenant_source_file",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "import_job_id"],
            ["import_jobs.tenant_id", "import_jobs.id"],
            name="fk_worker_jobs_tenant_import_job",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_worker_jobs"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_worker_jobs_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_worker_jobs_tenant_idempotency"),
    )
    op.create_index(
        "ix_worker_jobs_tenant_claim",
        "worker_jobs",
        ["tenant_id", "status", "available_at", "lease_expires_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant_context = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        for table in ("media_objects", "worker_jobs"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
                f'FOR ALL USING (tenant_id = {tenant_context}) '
                f'WITH CHECK (tenant_id = {tenant_context})'
            )


def downgrade() -> None:
    op.drop_table("worker_jobs")
    with op.batch_alter_table("source_files") as batch_op:
        batch_op.drop_constraint("fk_source_files_tenant_media", type_="foreignkey")
        batch_op.drop_constraint(
            "security_status_allowed", type_="check"
        )
        batch_op.drop_column("security_status")
        batch_op.drop_column("media_object_id")
    op.drop_table("media_objects")
