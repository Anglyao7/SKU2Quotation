"""Phase 4A-1A Product Intelligence contracts and fake pipeline persistence.

Revision ID: 20260718_0009
Revises: 20260718_0008
Requirements: AIPI-001, AIPI-002, AIPI-004, AIPI-009, AIPI-010,
AITASK-001, AITASK-002, AITASK-003, AITASK-004, AIPROD-001, AIPROD-002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0009"
down_revision = "20260718_0008"
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
    _create_ai_runs()
    _create_ai_task_steps()
    _create_product_field_candidates()
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_rls()


def _create_ai_runs() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("ai_task_id", _uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("adapter_key", sa.String(120), nullable=False),
        sa.Column("adapter_version", sa.String(50), nullable=False),
        sa.Column("provider_type", sa.String(20), nullable=False, server_default="FAKE"),
        sa.Column("status", sa.String(30), nullable=False, server_default="CREATED"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("usage", JSON_DOCUMENT, nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_runs_attempt_number_positive"),
        sa.CheckConstraint(
            "length(input_hash) = 64", name="ck_ai_runs_input_hash_sha256_length"
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="ck_ai_runs_output_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "(output_ref IS NULL AND output_hash IS NULL) OR "
            "(output_ref IS NOT NULL AND output_hash IS NOT NULL)",
            name="ck_ai_runs_output_reference_complete",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_runs_duration_nonnegative",
        ),
        sa.CheckConstraint("record_version >= 1", name="ck_ai_runs_record_version_positive"),
        sa.CheckConstraint("provider_type IN ('FAKE')", name="ck_ai_runs_provider_type_allowed"),
        sa.CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_ai_runs_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_ai_runs_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_ai_runs_tenant_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_runs"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_runs_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id", "ai_task_id", "attempt_number", name="uq_ai_runs_task_attempt"
        ),
    )
    op.create_index(
        "ix_ai_runs_tenant_task_status",
        "ai_runs",
        ["tenant_id", "ai_task_id", "status"],
    )


def _create_ai_task_steps() -> None:
    op.create_table(
        "ai_task_steps",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("ai_task_id", _uuid(), nullable=False),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("step_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_id", _uuid(), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "step_version >= 1", name="ck_ai_task_steps_step_version_positive"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_ai_task_steps_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64", name="ck_ai_task_steps_input_hash_sha256_length"
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="ck_ai_task_steps_output_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "(output_ref IS NULL AND output_hash IS NULL) OR "
            "(output_ref IS NOT NULL AND output_hash IS NOT NULL)",
            name="ck_ai_task_steps_output_reference_complete",
        ),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_ai_task_steps_record_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_ai_task_steps_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_ai_task_steps_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_ai_task_steps_tenant_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "last_run_id"],
            ["ai_runs.tenant_id", "ai_runs.id"],
            name="fk_ai_task_steps_tenant_last_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_task_steps"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_task_steps_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "ai_task_id",
            "step_key",
            "step_version",
            name="uq_ai_task_steps_task_step_version",
        ),
    )
    op.create_index(
        "ix_ai_task_steps_tenant_task_status",
        "ai_task_steps",
        ["tenant_id", "ai_task_id", "status"],
    )


def _create_product_field_candidates() -> None:
    op.create_table(
        "product_field_candidates",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("ai_task_id", _uuid(), nullable=False),
        sa.Column("ai_run_id", _uuid(), nullable=False),
        sa.Column("source_evidence_id", _uuid(), nullable=False),
        sa.Column("candidate_group_key", sa.String(160), nullable=False),
        sa.Column("candidate_index", sa.Integer(), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", JSON_DOCUMENT, nullable=False),
        sa.Column("normalized_unit", sa.String(40), nullable=True),
        sa.Column("source_language", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("confidence_policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("extractor_key", sa.String(120), nullable=False),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("validation_status", sa.String(30), nullable=False, server_default="PASS"),
        sa.Column(
            "review_status", sa.String(30), nullable=False, server_default="AI_SUGGESTED"
        ),
        sa.Column("warnings", JSON_DOCUMENT, nullable=False),
        sa.Column("candidate_hash", sa.String(64), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "candidate_index >= 0",
            name="ck_product_field_candidates_candidate_index_nonnegative",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_product_field_candidates_confidence_range",
        ),
        sa.CheckConstraint(
            "confidence_policy_version >= 1",
            name="ck_product_field_candidates_confidence_policy_version_positive",
        ),
        sa.CheckConstraint(
            "length(candidate_hash) = 64",
            name="ck_product_field_candidates_candidate_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "record_version >= 1",
            name="ck_product_field_candidates_record_version_positive",
        ),
        sa.CheckConstraint(
            "validation_status IN ('PASS', 'WARNING', 'FAILED')",
            name="ck_product_field_candidates_validation_status_allowed",
        ),
        sa.CheckConstraint(
            "review_status = 'AI_SUGGESTED'",
            name="ck_product_field_candidates_review_status_candidate_only",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_field_candidates_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_product_field_candidates_tenant_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_run_id"],
            ["ai_runs.tenant_id", "ai_runs.id"],
            name="fk_product_field_candidates_tenant_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_product_field_candidates_tenant_evidence",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_field_candidates"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_product_field_candidates_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "ai_task_id",
            "candidate_group_key",
            "field_key",
            "candidate_hash",
            name="uq_product_field_candidates_task_field_hash",
        ),
    )
    op.create_index(
        "ix_product_field_candidates_tenant_task_review",
        "product_field_candidates",
        ["tenant_id", "ai_task_id", "review_status"],
    )


def _enable_postgresql_rls() -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in ("ai_runs", "ai_task_steps", "product_field_candidates"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("product_field_candidates", "ai_task_steps", "ai_runs"):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
    op.drop_table("product_field_candidates")
    op.drop_table("ai_task_steps")
    op.drop_table("ai_runs")
