"""Phase 4A-1C deterministic normalization and human-confirmed Product adoption.

Revision ID: 20260718_0011
Revises: 20260718_0010
Requirements: AIPI-002, AIPI-003, AIPI-004, AIPI-010, DB-PROD-003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0011"
down_revision = "20260718_0010"
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
    op.add_column(
        "product_field_candidates",
        sa.Column(
            "normalization_rule_version",
            sa.String(80),
            nullable=False,
            server_default="raw-v1",
        ),
    )
    op.add_column(
        "product_field_candidates",
        sa.Column(
            "normalization_trace",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    _create_product_candidate_decisions()
    _create_product_versions()
    _create_outbox_events()
    _enforce_product_version_append_only()
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_rls()


def _create_product_candidate_decisions() -> None:
    op.create_table(
        "product_candidate_decisions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("ai_task_id", _uuid(), nullable=False),
        sa.Column("candidate_group_key", sa.String(160), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("candidate_ids", JSON_DOCUMENT, nullable=False),
        sa.Column("human_values", JSON_DOCUMENT, nullable=False),
        sa.Column("normalization_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("normalization_rule_version", sa.String(80), nullable=False),
        sa.Column("reviewed_by_membership_id", _uuid(), nullable=False),
        sa.Column("expected_product_version", sa.BigInteger(), nullable=True),
        sa.Column("product_id", _uuid(), nullable=True),
        sa.Column("applied_product_version", sa.BigInteger(), nullable=True),
        sa.Column("change_reason", sa.String(500), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "action IN ('APPROVE', 'REJECT')",
            name="ck_product_candidate_decisions_action_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('RECORDED', 'APPLIED')",
            name="ck_product_candidate_decisions_status_allowed",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64",
            name="ck_product_candidate_decisions_input_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "expected_product_version IS NULL OR expected_product_version >= 1",
            name="ck_product_candidate_decisions_expected_product_version_positive",
        ),
        sa.CheckConstraint(
            "applied_product_version IS NULL OR applied_product_version >= 1",
            name="ck_product_candidate_decisions_applied_product_version_positive",
        ),
        sa.CheckConstraint(
            "record_version >= 1",
            name="ck_product_candidate_decisions_record_version_positive",
        ),
        sa.CheckConstraint(
            "(action = 'REJECT' AND status = 'RECORDED' "
            "AND product_id IS NULL AND applied_product_version IS NULL AND applied_at IS NULL) "
            "OR (action = 'APPROVE' AND status = 'APPLIED' "
            "AND product_id IS NOT NULL AND applied_product_version IS NOT NULL "
            "AND applied_at IS NOT NULL)",
            name="ck_product_candidate_decisions_decision_lifecycle_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_candidate_decisions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_product_candidate_decisions_tenant_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_product_candidate_decisions_tenant_reviewer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_candidate_decisions_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_candidate_decisions"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_product_candidate_decisions_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_product_candidate_decisions_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_product_candidate_decisions_tenant_task_group",
        "product_candidate_decisions",
        ["tenant_id", "ai_task_id", "candidate_group_key", "created_at"],
    )
    op.create_index(
        "uq_product_candidate_decisions_applied_group",
        "product_candidate_decisions",
        ["tenant_id", "ai_task_id", "candidate_group_key"],
        unique=True,
        postgresql_where=sa.text(
            "action = 'APPROVE' AND status = 'APPLIED' AND deleted_at IS NULL"
        ),
        sqlite_where=sa.text(
            "action = 'APPROVE' AND status = 'APPLIED' AND deleted_at IS NULL"
        ),
    )


def _create_product_versions() -> None:
    op.create_table(
        "product_versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("version_number", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("source_evidence_id", _uuid(), nullable=True),
        sa.Column("review_decision_id", _uuid(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_product_versions_version_number_positive"
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_product_versions_content_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_product_versions_record_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_versions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_versions_tenant_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_decision_id"],
            ["product_candidate_decisions.tenant_id", "product_candidate_decisions.id"],
            name="fk_product_versions_tenant_review_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_product_versions_tenant_source_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_product_versions_created_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_versions"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_versions_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "version_number",
            name="uq_product_versions_product_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "review_decision_id",
            name="uq_product_versions_review_decision",
        ),
    )
    op.create_index(
        "ix_product_versions_tenant_product_created",
        "product_versions",
        ["tenant_id", "product_id", "created_at"],
    )


def _create_outbox_events() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("decision_id", _uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(100), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("payload", JSON_DOCUMENT, nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("causation_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("last_error_message", sa.String(500), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_outbox_events_schema_version_positive"
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1", name="ck_outbox_events_aggregate_version_positive"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_outbox_events_attempt_count_nonnegative"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'FAILED')",
            name="ck_outbox_events_status_allowed",
        ),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_outbox_events_record_version_positive"
        ),
        sa.CheckConstraint(
            "(status = 'PUBLISHED' AND published_at IS NOT NULL) "
            "OR (status IN ('PENDING', 'FAILED') AND published_at IS NULL)",
            name="ck_outbox_events_publication_lifecycle_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_outbox_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["product_candidate_decisions.tenant_id", "product_candidate_decisions.id"],
            name="fk_outbox_events_tenant_decision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_outbox_events_aggregate_version",
        ),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["occurred_at", "id"],
        postgresql_where=sa.text("status IN ('PENDING', 'FAILED') AND deleted_at IS NULL"),
        sqlite_where=sa.text("status IN ('PENDING', 'FAILED') AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_events_tenant_status",
        "outbox_events",
        ["tenant_id", "status", "occurred_at"],
    )


def _enforce_product_version_append_only() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION atc_reject_product_version_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'product_versions are append-only'; END; $$"
        )
        op.execute(
            "CREATE TRIGGER product_versions_append_only "
            "BEFORE UPDATE OR DELETE ON product_versions FOR EACH ROW "
            "EXECUTE FUNCTION atc_reject_product_version_mutation()"
        )
    else:
        op.execute(
            "CREATE TRIGGER product_versions_append_only_update "
            "BEFORE UPDATE ON product_versions BEGIN "
            "SELECT RAISE(ABORT, 'product_versions are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER product_versions_append_only_delete "
            "BEFORE DELETE ON product_versions BEGIN "
            "SELECT RAISE(ABORT, 'product_versions are append-only'); END"
        )


def _enable_postgresql_rls() -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in ("product_candidate_decisions", "product_versions", "outbox_events"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("outbox_events", "product_versions", "product_candidate_decisions"):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
        op.execute("DROP TRIGGER IF EXISTS product_versions_append_only ON product_versions")
        op.execute("DROP FUNCTION IF EXISTS atc_reject_product_version_mutation()")
    op.drop_table("outbox_events")
    op.drop_table("product_versions")
    op.drop_table("product_candidate_decisions")
    with op.batch_alter_table("product_field_candidates") as batch_op:
        batch_op.drop_column("normalization_trace")
        batch_op.drop_column("normalization_rule_version")
