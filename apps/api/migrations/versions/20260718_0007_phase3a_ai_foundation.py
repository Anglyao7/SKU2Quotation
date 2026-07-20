"""Phase 3A AI governance data foundation.

Revision ID: 20260718_0007
Revises: 20260718_0006
Requirements: AITASK-001, AITASK-003, AITASK-004, AIDB-001, AIDB-003,
DB-AI-001, DB-AI-003, RLS-001, RLS-003, MIGDB-001, MIGDB-003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0007"
down_revision = "20260718_0006"
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
    _create_provider_routes()
    _create_ai_tasks()
    _create_source_evidence()
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_rls()


def _create_provider_routes() -> None:
    op.create_table(
        "ai_provider_routes",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("route_key", sa.String(100), nullable=False),
        sa.Column("route_version", sa.Integer(), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("primary_adapter", sa.String(160), nullable=False),
        sa.Column("fallback_adapters", JSON_DOCUMENT, nullable=False),
        sa.Column("data_region", sa.String(64), nullable=True),
        sa.Column("max_data_classification", sa.String(30), nullable=False),
        sa.Column("routing_policy", JSON_DOCUMENT, nullable=False),
        sa.Column("retention_policy", JSON_DOCUMENT, nullable=False),
        sa.Column("credential_secret_ref", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_membership_id", _uuid(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("route_version >= 1", name="ck_ai_provider_routes_route_version_positive"),
        sa.CheckConstraint("record_version >= 1", name="ck_ai_provider_routes_record_version_positive"),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'RETIRED')", name="ck_ai_provider_routes_status_allowed"),
        sa.CheckConstraint("max_data_classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')", name="ck_ai_provider_routes_classification_allowed"),
        sa.CheckConstraint("effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from", name="ck_ai_provider_routes_effective_period_valid"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_ai_provider_routes_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "approved_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_ai_provider_routes_tenant_approver", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_provider_routes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_provider_routes_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "route_key", "route_version", name="uq_ai_provider_routes_tenant_key_version"),
    )
    op.create_index(
        "ix_ai_provider_routes_tenant_capability_status",
        "ai_provider_routes",
        ["tenant_id", "capability", "status"],
    )


def _create_ai_tasks() -> None:
    op.create_table(
        "ai_tasks",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("business_entity_type", sa.String(80), nullable=True),
        sa.Column("business_entity_id", sa.String(100), nullable=True),
        sa.Column("business_entity_version", sa.BigInteger(), nullable=True),
        sa.Column("risk_level", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("input_schema_version", sa.Integer(), nullable=False),
        sa.Column("input_ref", sa.Text(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("budget_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("requested_by_membership_id", _uuid(), nullable=True),
        sa.Column("provider_route_id", _uuid(), nullable=True),
        sa.Column("route_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("safe_error_message", sa.String(500), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("task_version >= 1", name="ck_ai_tasks_task_version_positive"),
        sa.CheckConstraint("input_schema_version >= 1", name="ck_ai_tasks_input_schema_version_positive"),
        sa.CheckConstraint("business_entity_version IS NULL OR business_entity_version >= 1", name="ck_ai_tasks_entity_version_positive"),
        sa.CheckConstraint("record_version >= 1", name="ck_ai_tasks_record_version_positive"),
        sa.CheckConstraint("priority >= 0 AND priority <= 1000", name="ck_ai_tasks_priority_range"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_ai_tasks_progress_range"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_ai_tasks_input_hash_sha256_length"),
        sa.CheckConstraint("(business_entity_type IS NULL AND business_entity_id IS NULL) OR (business_entity_type IS NOT NULL AND business_entity_id IS NOT NULL)", name="ck_ai_tasks_entity_reference_complete"),
        sa.CheckConstraint("risk_level IN ('L1_ASSISTIVE', 'L2_DRAFTING', 'L3_DECISION_SUPPORT', 'L4_HIGH_IMPACT')", name="ck_ai_tasks_risk_level_allowed"),
        sa.CheckConstraint("status IN ('PENDING', 'QUEUED', 'RUNNING', 'VALIDATING', 'SUCCEEDED', 'NEEDS_REVIEW', 'PARTIAL', 'FAILED', 'CANCELLED', 'EXPIRED')", name="ck_ai_tasks_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_ai_tasks_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "requested_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_ai_tasks_tenant_requester", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "provider_route_id"], ["ai_provider_routes.tenant_id", "ai_provider_routes.id"], name="fk_ai_tasks_tenant_provider_route", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_tasks"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_tasks_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ai_tasks_tenant_idempotency"),
    )
    op.create_index(
        "ix_ai_tasks_tenant_status_priority_created",
        "ai_tasks",
        ["tenant_id", "status", "priority", "created_at"],
    )
    op.create_index(
        "ix_ai_tasks_tenant_business_entity",
        "ai_tasks",
        ["tenant_id", "business_entity_type", "business_entity_id"],
    )


def _create_source_evidence() -> None:
    op.create_table(
        "ai_source_evidence",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("ai_task_id", _uuid(), nullable=True),
        sa.Column("source_file_id", sa.String(40), nullable=True),
        sa.Column("source_entity_type", sa.String(80), nullable=False),
        sa.Column("source_entity_id", sa.String(100), nullable=False),
        sa.Column("source_version", sa.BigInteger(), nullable=True),
        sa.Column("location_type", sa.String(40), nullable=False),
        sa.Column("location", JSON_DOCUMENT, nullable=False),
        sa.Column("raw_value_ref", sa.Text(), nullable=True),
        sa.Column("raw_value_hash", sa.String(64), nullable=True),
        sa.Column("normalized_value_ref", sa.Text(), nullable=True),
        sa.Column("claim_summary", sa.String(500), nullable=True),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("permission_scope", JSON_DOCUMENT, nullable=False),
        sa.Column("parser_identifier", sa.String(100), nullable=True),
        sa.Column("parser_version", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("source_version IS NULL OR source_version >= 1", name="ck_ai_source_evidence_source_version_positive"),
        sa.CheckConstraint("record_version >= 1", name="ck_ai_source_evidence_record_version_positive"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_ai_source_evidence_confidence_range"),
        sa.CheckConstraint("raw_value_hash IS NULL OR length(raw_value_hash) = 64", name="ck_ai_source_evidence_raw_value_hash_sha256_length"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_ai_source_evidence_evidence_hash_sha256_length"),
        sa.CheckConstraint("raw_value_ref IS NULL OR raw_value_hash IS NOT NULL", name="ck_ai_source_evidence_raw_reference_has_hash"),
        sa.CheckConstraint("classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')", name="ck_ai_source_evidence_classification_allowed"),
        sa.CheckConstraint("location_type IN ('SHEET_CELL_RANGE', 'PAGE_BOX', 'SLIDE_SHAPE', 'IMAGE_CROP', 'ENTITY_FIELD', 'FILE_OBJECT')", name="ck_ai_source_evidence_location_type_allowed"),
        sa.CheckConstraint("(parser_identifier IS NULL AND parser_version IS NULL) OR (parser_identifier IS NOT NULL AND parser_version IS NOT NULL)", name="ck_ai_source_evidence_parser_reference_complete"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_ai_source_evidence_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "ai_task_id"], ["ai_tasks.tenant_id", "ai_tasks.id"], name="fk_ai_source_evidence_tenant_task", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "source_file_id"], ["source_files.tenant_id", "source_files.id"], name="fk_ai_source_evidence_tenant_source_file", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_source_evidence"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ai_source_evidence_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "source_entity_type", "source_entity_id", "location_type", "evidence_hash", name="uq_ai_source_evidence_tenant_source_hash"),
    )
    op.create_index(
        "ix_ai_source_evidence_tenant_task",
        "ai_source_evidence",
        ["tenant_id", "ai_task_id"],
    )
    op.create_index(
        "ix_ai_source_evidence_tenant_source",
        "ai_source_evidence",
        ["tenant_id", "source_entity_type", "source_entity_id"],
    )
    op.create_index(
        "ix_ai_source_evidence_tenant_file",
        "ai_source_evidence",
        ["tenant_id", "source_file_id"],
    )


def _enable_postgresql_rls() -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in ("ai_provider_routes", "ai_tasks", "ai_source_evidence"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("ai_source_evidence", "ai_tasks", "ai_provider_routes"):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
    op.drop_table("ai_source_evidence")
    op.drop_table("ai_tasks")
    op.drop_table("ai_provider_routes")
