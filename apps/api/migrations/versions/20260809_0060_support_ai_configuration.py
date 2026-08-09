"""Add configuration center generation model and traceable AI support runtime.

Revision ID: 20260809_0060
Revises: 20260809_0059
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql


revision = "20260809_0060"
down_revision = "20260809_0059"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)

PERMISSIONS = (
    (
        "support.ai.manage",
        "support_ai",
        "manage",
        "Manage customer-service AI policy and automation mode",
        ("OWNER", "ADMIN"),
    ),
    (
        "support.ai.inspect",
        "support_ai",
        "inspect",
        "Inspect customer-service AI runs, evidence, and decisions",
        ("OWNER", "ADMIN", "SALES"),
    ),
    (
        "support.ai.test",
        "support_ai",
        "test",
        "Run customer-service AI test-lab questions",
        ("OWNER", "ADMIN"),
    ),
    (
        "knowledge.manage",
        "knowledge",
        "manage",
        "Upload, reindex, and revoke customer-facing knowledge sources",
        ("OWNER", "ADMIN"),
    ),
    (
        "knowledge.approve",
        "knowledge",
        "approve",
        "Approve customer-facing knowledge sources for AI use",
        ("OWNER", "ADMIN"),
    ),
)


def _uuid_type() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _database_uuid() -> object:
    value = uuid4()
    return value if op.get_bind().dialect.name == "postgresql" else value.hex


def _audit_columns() -> tuple[sa.Column, sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def _enable_rls(table_name: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY "{table_name}_tenant_isolation" '
        f'ON "{table_name}" FOR ALL '
        f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
    )


def _provision_permissions() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"
    if is_postgresql:
        op.execute('ALTER TABLE "roles" NO FORCE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
    try:
        for code, module, action, description, role_codes in PERMISSIONS:
            permission_id = bind.execute(
                sa.text("SELECT id FROM permissions WHERE code = :code"),
                {"code": code},
            ).scalar_one_or_none()
            if permission_id is None:
                permission_id = _database_uuid()
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO permissions (
                            id, code, module, action, description,
                            created_at, updated_at, deleted_at
                        ) VALUES (
                            :id, :code, :module, :action, :description,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                        )
                        """
                    ),
                    {
                        "id": permission_id,
                        "code": code,
                        "module": module,
                        "action": action,
                        "description": description,
                    },
                )
            else:
                bind.execute(
                    sa.text(
                        """
                        UPDATE permissions
                        SET module = :module, action = :action,
                            description = :description,
                            updated_at = CURRENT_TIMESTAMP, deleted_at = NULL
                        WHERE id = :permission_id
                        """
                    ),
                    {
                        "permission_id": permission_id,
                        "module": module,
                        "action": action,
                        "description": description,
                    },
                )
            roles = bind.execute(
                sa.text(
                    """
                    SELECT id, tenant_id FROM roles
                    WHERE code IN :role_codes
                      AND status = 'active' AND deleted_at IS NULL
                    """
                ).bindparams(sa.bindparam("role_codes", expanding=True)),
                {"role_codes": list(role_codes)},
            ).all()
            for role_id, tenant_id in roles:
                assignment = bind.execute(
                    sa.text(
                        """
                        SELECT id FROM role_permissions
                        WHERE tenant_id = :tenant_id AND role_id = :role_id
                          AND permission_id = :permission_id
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "role_id": role_id,
                        "permission_id": permission_id,
                    },
                ).scalar_one_or_none()
                if assignment is None:
                    bind.execute(
                        sa.text(
                            """
                            INSERT INTO role_permissions (
                                id, tenant_id, role_id, permission_id,
                                created_at, updated_at, deleted_at
                            ) VALUES (
                                :id, :tenant_id, :role_id, :permission_id,
                                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                            )
                            """
                        ),
                        {
                            "id": _database_uuid(),
                            "tenant_id": tenant_id,
                            "role_id": role_id,
                            "permission_id": permission_id,
                        },
                    )
                else:
                    bind.execute(
                        sa.text(
                            """
                            UPDATE role_permissions
                            SET updated_at = CURRENT_TIMESTAMP, deleted_at = NULL
                            WHERE id = :assignment
                            """
                        ),
                        {"assignment": assignment},
                    )
    finally:
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')
            op.execute('ALTER TABLE "roles" FORCE ROW LEVEL SECURITY')


def upgrade() -> None:
    with op.batch_alter_table("storefront_chat_conversations") as batch:
        batch.add_column(
            sa.Column(
                "automation_state",
                sa.String(30),
                nullable=False,
                server_default="AI_ACTIVE",
            )
        )
        batch.add_column(
            sa.Column(
                "automation_state_changed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_storefront_chat_conversations_automation_state_allowed",
            "automation_state IN ('AI_ACTIVE', 'HUMAN_TAKEOVER')",
        )

    op.create_table(
        "support_ai_provider_settings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column(
            "provider",
            sa.String(40),
            nullable=False,
            server_default="openai-compatible",
        ),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("model_name", sa.String(300), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="45"),
        sa.Column(
            "max_output_tokens", sa.Integer(), nullable=False, server_default="2048"
        ),
        sa.Column(
            "temperature", sa.Numeric(4, 3), nullable=False, server_default="0.100"
        ),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_last_four", sa.String(4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", _uuid_type(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "provider = 'openai-compatible'",
            name="ck_support_ai_provider_settings_provider_supported",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 180",
            name="ck_support_ai_provider_settings_timeout_supported",
        ),
        sa.CheckConstraint(
            "max_output_tokens >= 128 AND max_output_tokens <= 32768",
            name="ck_support_ai_provider_settings_max_output_tokens_supported",
        ),
        sa.CheckConstraint(
            "temperature >= 0 AND temperature <= 2",
            name="ck_support_ai_provider_settings_temperature_supported",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_support_ai_provider_settings_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_support_ai_provider_settings_updated_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_provider_settings"),
    )

    op.create_table(
        "support_ai_settings",
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False, server_default="OFF"),
        sa.Column(
            "sku_knowledge_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "file_knowledge_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "multilingual_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "min_retrieval_score",
            sa.Numeric(6, 5),
            nullable=False,
            server_default="0.12000",
        ),
        sa.Column(
            "min_answer_confidence",
            sa.Numeric(6, 5),
            nullable=False,
            server_default="0.65000",
        ),
        sa.Column("max_sources", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "daily_auto_reply_limit", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column(
            "handoff_messages",
            JSON_DOCUMENT,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("prompt_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by_user_id", _uuid_type(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "mode IN ('OFF', 'DRAFT', 'SHADOW', 'AUTO_LIMITED', 'AUTO')",
            name="ck_support_ai_settings_mode_allowed",
        ),
        sa.CheckConstraint(
            "min_retrieval_score >= 0 AND min_retrieval_score <= 1",
            name="ck_support_ai_settings_retrieval_score_range",
        ),
        sa.CheckConstraint(
            "min_answer_confidence >= 0 AND min_answer_confidence <= 1",
            name="ck_support_ai_settings_answer_confidence_range",
        ),
        sa.CheckConstraint(
            "max_sources >= 1 AND max_sources <= 12",
            name="ck_support_ai_settings_max_sources_range",
        ),
        sa.CheckConstraint(
            "daily_auto_reply_limit >= 1 AND daily_auto_reply_limit <= 100000",
            name="ck_support_ai_settings_daily_limit_range",
        ),
        sa.CheckConstraint(
            "prompt_version >= 1",
            name="ck_support_ai_settings_prompt_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_settings_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name="fk_support_ai_settings_updated_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_support_ai_settings"),
        sa.UniqueConstraint("tenant_id", name="uq_support_ai_settings_tenant"),
    )

    op.create_table(
        "support_ai_knowledge_sources",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="FILE"),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "classification",
            sa.String(30),
            nullable=False,
            server_default="CUSTOMER_APPROVED",
        ),
        sa.Column("language", sa.String(35), nullable=False, server_default="und"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROCESSING"),
        sa.Column("media_object_id", _uuid_type(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_message", sa.String(500), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", _uuid_type(), nullable=True),
        sa.Column("created_by_user_id", _uuid_type(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "source_type = 'FILE'",
            name="ck_support_ai_knowledge_sources_source_type_allowed",
        ),
        sa.CheckConstraint(
            "classification IN ('PUBLIC', 'CUSTOMER_APPROVED')",
            name="ck_support_ai_knowledge_sources_classification_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'READY', 'APPROVED', 'REVOKED', 'FAILED')",
            name="ck_support_ai_knowledge_sources_status_allowed",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_support_ai_knowledge_sources_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_knowledge_sources_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "media_object_id"],
            ["media_objects.tenant_id", "media_objects.id"],
            name="fk_support_ai_knowledge_sources_tenant_media",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name="fk_support_ai_knowledge_sources_approver",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_support_ai_knowledge_sources_creator",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_knowledge_sources"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_support_ai_knowledge_sources_tenant_identity",
        ),
    )
    op.create_index(
        "ix_support_ai_knowledge_sources_tenant_status",
        "support_ai_knowledge_sources",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "support_ai_knowledge_chunks",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("source_id", _uuid_type(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_path", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("language", sa.String(35), nullable=False, server_default="und"),
        sa.Column("locator", JSON_DOCUMENT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("embedding", JSON_DOCUMENT, nullable=True),
        sa.Column("embedding_provider", sa.String(100), nullable=True),
        sa.Column("embedding_model", sa.String(300), nullable=True),
        sa.Column("embedding_version", sa.String(120), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        *_audit_columns(),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_support_ai_knowledge_chunks_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "token_count >= 0",
            name="ck_support_ai_knowledge_chunks_token_count_nonnegative",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_support_ai_knowledge_chunks_content_hash_length",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'DELETED')",
            name="ck_support_ai_knowledge_chunks_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_knowledge_chunks_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_knowledge_chunks_tenant_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_knowledge_chunks"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_support_ai_knowledge_chunks_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_id",
            "chunk_index",
            name="uq_support_ai_knowledge_chunks_source_order",
        ),
    )
    op.create_index(
        "ix_support_ai_knowledge_chunks_tenant_source_status",
        "support_ai_knowledge_chunks",
        ["tenant_id", "source_id", "status"],
    )

    op.create_table(
        "support_ai_ingestion_jobs",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("source_id", _uuid_type(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parser_identifier", sa.String(100), nullable=True),
        sa.Column("parser_version", sa.String(50), nullable=True),
        sa.Column("chunks_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("requested_by_user_id", _uuid_type(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_support_ai_ingestion_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100",
            name="ck_support_ai_ingestion_jobs_progress_range",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_ingestion_jobs_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_ingestion_jobs_tenant_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_support_ai_ingestion_jobs_requester",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_ingestion_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_support_ai_ingestion_jobs_tenant_identity",
        ),
    )
    op.create_index(
        "ix_support_ai_ingestion_jobs_tenant_created",
        "support_ai_ingestion_jobs",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "support_ai_runs",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("ai_task_id", _uuid_type(), nullable=False),
        sa.Column("conversation_id", _uuid_type(), nullable=True),
        sa.Column("input_message_id", _uuid_type(), nullable=True),
        sa.Column("output_message_id", _uuid_type(), nullable=True),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("mode_snapshot", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="QUEUED"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("visitor_locale", sa.String(35), nullable=False, server_default="und"),
        sa.Column("detected_language", sa.String(35), nullable=True),
        sa.Column("normalized_query", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(6, 5), nullable=True),
        sa.Column("handoff_reason", sa.String(160), nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("model_name", sa.String(300), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retrieval_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "decision_trace", JSON_DOCUMENT, nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "trigger_type IN ('CHAT', 'TEST')",
            name="ck_support_ai_runs_trigger_type_allowed",
        ),
        sa.CheckConstraint(
            "mode_snapshot IN ('OFF', 'DRAFT', 'SHADOW', 'AUTO_LIMITED', 'AUTO')",
            name="ck_support_ai_runs_mode_snapshot_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'NEEDS_REVIEW', "
            "'HANDOFF', 'FAILED', 'CANCELLED', 'SKIPPED')",
            name="ck_support_ai_runs_status_allowed",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_support_ai_runs_confidence_range",
        ),
        sa.CheckConstraint(
            "prompt_version >= 1",
            name="ck_support_ai_runs_prompt_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_runs_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_task_id"],
            ["ai_tasks.tenant_id", "ai_tasks.id"],
            name="fk_support_ai_runs_tenant_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["storefront_chat_conversations.tenant_id", "storefront_chat_conversations.id"],
            name="fk_support_ai_runs_tenant_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "input_message_id"],
            ["storefront_chat_messages.tenant_id", "storefront_chat_messages.id"],
            name="fk_support_ai_runs_tenant_input_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "output_message_id"],
            ["storefront_chat_messages.tenant_id", "storefront_chat_messages.id"],
            name="fk_support_ai_runs_tenant_output_message",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_runs"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_support_ai_runs_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id", "ai_task_id", name="uq_support_ai_runs_tenant_task"
        ),
    )
    op.create_index(
        "ix_support_ai_runs_tenant_status_created",
        "support_ai_runs",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "uq_support_ai_runs_input_message",
        "support_ai_runs",
        ["tenant_id", "input_message_id"],
        unique=True,
        postgresql_where=sa.text("input_message_id IS NOT NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("input_message_id IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_table(
        "support_ai_evidence_uses",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("tenant_id", _uuid_type(), nullable=False),
        sa.Column("run_id", _uuid_type(), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("knowledge_source_id", _uuid_type(), nullable=True),
        sa.Column("source_entity_id", sa.String(120), nullable=False),
        sa.Column("source_title", sa.String(500), nullable=False),
        sa.Column("source_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("locator", JSON_DOCUMENT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("score", sa.Numeric(6, 5), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "citation_number >= 1",
            name="ck_support_ai_evidence_uses_citation_number_positive",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_support_ai_evidence_uses_score_range",
        ),
        sa.CheckConstraint(
            "source_type IN ('SKU', 'FILE')",
            name="ck_support_ai_evidence_uses_source_type_allowed",
        ),
        sa.CheckConstraint(
            "classification IN ('PUBLIC', 'CUSTOMER_APPROVED')",
            name="ck_support_ai_evidence_uses_classification_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_support_ai_evidence_uses_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["support_ai_runs.tenant_id", "support_ai_runs.id"],
            name="fk_support_ai_evidence_uses_tenant_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_source_id"],
            ["support_ai_knowledge_sources.tenant_id", "support_ai_knowledge_sources.id"],
            name="fk_support_ai_evidence_uses_tenant_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_support_ai_evidence_uses"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_support_ai_evidence_uses_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "citation_number",
            name="uq_support_ai_evidence_uses_run_citation",
        ),
    )
    op.create_index(
        "ix_support_ai_evidence_uses_tenant_run",
        "support_ai_evidence_uses",
        ["tenant_id", "run_id"],
    )

    for table_name in (
        "support_ai_settings",
        "support_ai_knowledge_sources",
        "support_ai_knowledge_chunks",
        "support_ai_ingestion_jobs",
        "support_ai_runs",
        "support_ai_evidence_uses",
    ):
        _enable_rls(table_name)

    if not context.is_offline_mode():
        _provision_permissions()


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        is_postgresql = bind.dialect.name == "postgresql"
        if is_postgresql:
            op.execute('ALTER TABLE "role_permissions" NO FORCE ROW LEVEL SECURITY')
        try:
            codes = tuple(row[0] for row in PERMISSIONS)
            bind.execute(
                sa.text(
                    """
                    DELETE FROM role_permissions
                    WHERE permission_id IN (
                        SELECT id FROM permissions WHERE code IN :codes
                    )
                    """
                ).bindparams(sa.bindparam("codes", expanding=True)),
                {"codes": list(codes)},
            )
            bind.execute(
                sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
                    sa.bindparam("codes", expanding=True)
                ),
                {"codes": list(codes)},
            )
        finally:
            if is_postgresql:
                op.execute('ALTER TABLE "role_permissions" FORCE ROW LEVEL SECURITY')

    op.drop_index(
        "ix_support_ai_evidence_uses_tenant_run",
        table_name="support_ai_evidence_uses",
    )
    op.drop_table("support_ai_evidence_uses")
    op.drop_index("uq_support_ai_runs_input_message", table_name="support_ai_runs")
    op.drop_index(
        "ix_support_ai_runs_tenant_status_created", table_name="support_ai_runs"
    )
    op.drop_table("support_ai_runs")
    op.drop_index(
        "ix_support_ai_ingestion_jobs_tenant_created",
        table_name="support_ai_ingestion_jobs",
    )
    op.drop_table("support_ai_ingestion_jobs")
    op.drop_index(
        "ix_support_ai_knowledge_chunks_tenant_source_status",
        table_name="support_ai_knowledge_chunks",
    )
    op.drop_table("support_ai_knowledge_chunks")
    op.drop_index(
        "ix_support_ai_knowledge_sources_tenant_status",
        table_name="support_ai_knowledge_sources",
    )
    op.drop_table("support_ai_knowledge_sources")
    op.drop_table("support_ai_settings")
    op.drop_table("support_ai_provider_settings")

    with op.batch_alter_table("storefront_chat_conversations") as batch:
        batch.drop_constraint(
            "ck_storefront_chat_conversations_automation_state_allowed",
            type_="check",
        )
        batch.drop_column("automation_state_changed_at")
        batch.drop_column("automation_state")
