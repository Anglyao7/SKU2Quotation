"""Phase 3B product knowledge and embedding foundation.

Revision ID: 20260718_0008
Revises: 20260718_0007
Requirements: AIKB-001, AIKB-002, AIKB-003, AIKB-004, AIKB-005,
AIDATA-001, AIDATA-002, AIDATA-003, AISEARCH-001, AISEARCH-002,
DB-AI-002, IDX-002, RLS-001
"""
from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0008"
down_revision = "20260718_0007"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
VECTOR_VALUE = VECTOR().with_variant(sa.JSON(), "sqlite")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _create_knowledge_documents()
    _create_knowledge_chunks()
    _create_embeddings()
    if dialect == "postgresql":
        _create_postgresql_search_indexes()
        _enable_postgresql_rls()


def _create_knowledge_documents() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("source_entity_type", sa.String(40), nullable=False),
        sa.Column("source_entity_id", _uuid(), nullable=False),
        sa.Column("source_version", sa.BigInteger(), nullable=False),
        sa.Column("document_type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("field_policy_version", sa.Integer(), nullable=False),
        sa.Column("canonical_payload", JSON_DOCUMENT, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("permission_scope", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "source_entity_type = 'PRODUCT'",
            name="ck_knowledge_documents_source_entity_type_allowed",
        ),
        sa.CheckConstraint(
            "source_version >= 1",
            name="ck_knowledge_documents_source_version_positive",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_knowledge_documents_schema_version_positive",
        ),
        sa.CheckConstraint(
            "field_policy_version >= 1",
            name="ck_knowledge_documents_field_policy_version_positive",
        ),
        sa.CheckConstraint(
            "record_version >= 1",
            name="ck_knowledge_documents_record_version_positive",
        ),
        sa.CheckConstraint(
            "classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')",
            name="ck_knowledge_documents_classification_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="ck_knowledge_documents_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_knowledge_documents_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_entity_id"],
            ["products.tenant_id", "products.id"],
            name="fk_knowledge_documents_tenant_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_documents"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_knowledge_documents_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_entity_type",
            "source_entity_id",
            "source_version",
            "schema_version",
            "field_policy_version",
            "locale",
            "content_hash",
            name="uq_knowledge_documents_projection",
        ),
    )
    op.create_index(
        "ix_knowledge_documents_tenant_source_status",
        "knowledge_documents",
        ["tenant_id", "source_entity_type", "source_entity_id", "status"],
    )
    op.create_index(
        "uq_knowledge_documents_active_source",
        "knowledge_documents",
        ["tenant_id", "source_entity_type", "source_entity_id", "locale"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"),
        sqlite_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"),
    )


def _create_knowledge_chunks() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("document_id", _uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(40), nullable=False),
        sa.Column("section_path", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("metadata", JSON_DOCUMENT, nullable=False),
        sa.Column("permission_scope", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "chunk_index >= 0", name="ck_knowledge_chunks_chunk_index_nonnegative"
        ),
        sa.CheckConstraint(
            "token_count >= 0", name="ck_knowledge_chunks_token_count_nonnegative"
        ),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_knowledge_chunks_record_version_positive"
        ),
        sa.CheckConstraint(
            "chunk_type IN ('OVERVIEW', 'SPECIFICATIONS', 'FEATURES', 'MARKETS', 'SUPPLY')",
            name="ck_knowledge_chunks_chunk_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="ck_knowledge_chunks_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_knowledge_chunks_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["knowledge_documents.tenant_id", "knowledge_documents.id"],
            name="fk_knowledge_chunks_tenant_document",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_chunks"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_knowledge_chunks_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_order",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_tenant_document_status",
        "knowledge_chunks",
        ["tenant_id", "document_id", "status"],
    )
    op.create_index(
        "ix_knowledge_chunks_content_hash",
        "knowledge_chunks",
        ["tenant_id", "content_hash"],
    )


def _create_embeddings() -> None:
    op.create_table(
        "embeddings",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.BigInteger(), nullable=False),
        sa.Column("embedding_type", sa.String(40), nullable=False),
        sa.Column("model_provider", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", VECTOR_VALUE, nullable=False),
        sa.Column("permission_scope", JSON_DOCUMENT, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint(
            "entity_type = 'KNOWLEDGE_CHUNK'",
            name="ck_embeddings_entity_type_allowed",
        ),
        sa.CheckConstraint(
            "entity_version >= 1", name="ck_embeddings_entity_version_positive"
        ),
        sa.CheckConstraint(
            "dimensions >= 1 AND dimensions <= 2000",
            name="ck_embeddings_dimensions_supported",
        ),
        sa.CheckConstraint(
            "record_version >= 1", name="ck_embeddings_record_version_positive"
        ),
        sa.CheckConstraint(
            "embedding_type IN ('TEXT', 'KNOWLEDGE_CHUNK')",
            name="ck_embeddings_embedding_type_allowed",
        ),
        sa.CheckConstraint(
            "distance_metric IN ('COSINE', 'L2', 'INNER_PRODUCT')",
            name="ck_embeddings_distance_metric_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')",
            name="ck_embeddings_status_allowed",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR activated_at IS NULL OR superseded_at >= activated_at",
            name="ck_embeddings_lifecycle_period_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_embeddings_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entity_id"],
            ["knowledge_chunks.tenant_id", "knowledge_chunks.id"],
            name="fk_embeddings_tenant_chunk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embeddings"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_embeddings_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            "entity_id",
            "entity_version",
            "embedding_type",
            "model_provider",
            "model_name",
            "model_version",
            "content_hash",
            name="uq_embeddings_projection",
        ),
    )
    op.create_index(
        "ix_embeddings_tenant_model_status",
        "embeddings",
        ["tenant_id", "model_name", "model_version", "dimensions", "status"],
    )
    op.create_index(
        "uq_embeddings_active_entity_model",
        "embeddings",
        [
            "tenant_id",
            "entity_type",
            "entity_id",
            "embedding_type",
            "model_provider",
            "model_name",
            "model_version",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"),
        sqlite_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"),
    )


def _create_postgresql_search_indexes() -> None:
    op.execute(
        "ALTER TABLE embeddings ADD CONSTRAINT ck_embeddings_vector_dimensions_match "
        "CHECK (vector_dims(embedding) = dimensions)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_content_fts ON knowledge_chunks "
        "USING gin (to_tsvector('simple', content)) "
        "WHERE status = 'ACTIVE' AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_embeddings_phase3b_hnsw_384 ON embeddings "
        "USING hnsw ((embedding::vector(384)) vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE status = 'ACTIVE' AND deleted_at IS NULL "
        "AND model_provider = 'local' "
        "AND model_name = 'atc-feature-hash' "
        "AND model_version = '1' AND dimensions = 384"
    )


def _enable_postgresql_rls() -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in ("knowledge_documents", "knowledge_chunks", "embeddings"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("embeddings", "knowledge_chunks", "knowledge_documents"):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
    op.drop_table("embeddings")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    # The vector extension may be shared by future revisions or applications and is intentionally retained.
