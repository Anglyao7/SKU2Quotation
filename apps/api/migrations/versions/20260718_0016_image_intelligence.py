"""Add provider-neutral Vision observations and image embeddings.

Revision ID: 20260718_0016
Revises: 20260718_0015
"""

from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0016"
down_revision = "20260718_0015"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
VECTOR_VALUE = VECTOR().with_variant(sa.JSON(), "sqlite")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def _audit() -> list[sa.Column]:
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)]


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "vision_observations",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("product_image_id", _uuid(), nullable=False), sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("model_provider", sa.String(100), nullable=False), sa.Column("model_name", sa.String(160), nullable=False), sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("labels", JSON_DOCUMENT, nullable=False), sa.Column("risks", JSON_DOCUMENT, nullable=False), sa.Column("quality_score", sa.Numeric(5, 4), nullable=False), sa.Column("status", sa.String(20), nullable=False), *_audit(),
        sa.CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="ck_vision_observations_quality_score_range"), sa.CheckConstraint("status IN ('OBSERVED', 'FAILED', 'STALE', 'ARCHIVED')", name="ck_vision_observations_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_vision_observations_tenant", ondelete="CASCADE"), sa.ForeignKeyConstraint(["tenant_id", "product_image_id"], ["product_images.tenant_id", "product_images.id"], name="fk_vision_observations_tenant_image", ondelete="CASCADE"), sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_vision_observations_tenant_product", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_vision_observations_tenant_identity"), sa.UniqueConstraint("tenant_id", "product_image_id", "model_provider", "model_name", "model_version", "content_hash", name="uq_vision_observations_projection"),
    )
    op.create_index("ix_vision_observations_tenant_image_status", "vision_observations", ["tenant_id", "product_image_id", "status"])
    op.create_table(
        "image_embeddings",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("product_image_id", _uuid(), nullable=False), sa.Column("product_id", _uuid(), nullable=False), sa.Column("product_version", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("model_provider", sa.String(100), nullable=False), sa.Column("model_name", sa.String(160), nullable=False), sa.Column("model_version", sa.String(80), nullable=False), sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("distance_metric", sa.String(20), nullable=False), sa.Column("embedding", VECTOR_VALUE, nullable=False),
        sa.Column("quality_score", sa.Numeric(5, 4), nullable=False), sa.Column("permission_scope", JSON_DOCUMENT, nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True), *_audit(),
        sa.CheckConstraint("product_version >= 1", name="ck_image_embeddings_product_version_positive"), sa.CheckConstraint("dimensions = 384", name="ck_image_embeddings_dimensions_supported"), sa.CheckConstraint("distance_metric = 'COSINE'", name="ck_image_embeddings_distance_metric_allowed"), sa.CheckConstraint("quality_score >= 0 AND quality_score <= 1", name="ck_image_embeddings_quality_score_range"), sa.CheckConstraint("status IN ('ACTIVE', 'STALE', 'FAILED', 'ARCHIVED', 'DELETED')", name="ck_image_embeddings_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_image_embeddings_tenant", ondelete="CASCADE"), sa.ForeignKeyConstraint(["tenant_id", "product_image_id"], ["product_images.tenant_id", "product_images.id"], name="fk_image_embeddings_tenant_image", ondelete="CASCADE"), sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_image_embeddings_tenant_product", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_image_embeddings_tenant_identity"), sa.UniqueConstraint("tenant_id", "product_image_id", "model_provider", "model_name", "model_version", "content_hash", name="uq_image_embeddings_projection"),
    )
    op.create_index("ix_image_embeddings_tenant_model_status", "image_embeddings", ["tenant_id", "model_name", "model_version", "status"])
    op.create_index("uq_image_embeddings_active_image_model", "image_embeddings", ["tenant_id", "product_image_id", "model_provider", "model_name", "model_version"], unique=True, postgresql_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"), sqlite_where=sa.text("status = 'ACTIVE' AND deleted_at IS NULL"))
    op.create_table(
        "image_searches",
        sa.Column("id", _uuid(), primary_key=True), sa.Column("tenant_id", _uuid(), nullable=False), sa.Column("requested_by_membership_id", _uuid(), nullable=False), sa.Column("query_object_key", sa.String(1024), nullable=False), sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("model_provider", sa.String(100), nullable=False), sa.Column("model_name", sa.String(160), nullable=False), sa.Column("model_version", sa.String(80), nullable=False), sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("query_embedding", VECTOR_VALUE, nullable=False), sa.Column("result_snapshot", JSON_DOCUMENT, nullable=False), sa.Column("warnings", JSON_DOCUMENT, nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), *_audit(),
        sa.CheckConstraint("dimensions = 384", name="ck_image_searches_dimensions_supported"), sa.CheckConstraint("status IN ('COMPLETED', 'NO_RELIABLE_MATCH', 'FAILED', 'EXPIRED')", name="ck_image_searches_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_image_searches_tenant", ondelete="CASCADE"), sa.ForeignKeyConstraint(["tenant_id", "requested_by_membership_id"], ["memberships.tenant_id", "memberships.id"], name="fk_image_searches_tenant_requester", ondelete="RESTRICT"), sa.UniqueConstraint("tenant_id", "id", name="uq_image_searches_tenant_identity"),
    )
    op.create_index("ix_image_searches_tenant_expiry", "image_searches", ["tenant_id", "status", "expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE image_embeddings ADD CONSTRAINT ck_image_embeddings_vector_dimensions_match CHECK (vector_dims(embedding) = dimensions)")
        op.execute("ALTER TABLE image_searches ADD CONSTRAINT ck_image_searches_vector_dimensions_match CHECK (vector_dims(query_embedding) = dimensions)")
        op.execute("CREATE INDEX ix_image_embeddings_hnsw_384 ON image_embeddings USING hnsw ((embedding::vector(384)) vector_cosine_ops) WITH (m = 16, ef_construction = 64) WHERE status = 'ACTIVE' AND deleted_at IS NULL AND dimensions = 384")
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        for table in ("vision_observations", "image_embeddings", "image_searches"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"CREATE POLICY {table}_tenant_isolation ON {table} FOR ALL USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})")
        op.execute("CREATE FUNCTION atc_guard_active_image_embedding() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.status = 'ACTIVE' AND NOT EXISTS (SELECT 1 FROM product_images p WHERE p.tenant_id=NEW.tenant_id AND p.id=NEW.product_image_id AND p.approval_status='APPROVED' AND p.deleted_at IS NULL) THEN RAISE EXCEPTION 'active image embedding requires APPROVED product image'; END IF; RETURN NEW; END $$")
        op.execute("CREATE TRIGGER trg_guard_active_image_embedding BEFORE INSERT OR UPDATE OF status, product_image_id ON image_embeddings FOR EACH ROW EXECUTE FUNCTION atc_guard_active_image_embedding()")
        op.execute("CREATE FUNCTION atc_stale_image_embedding() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.approval_status='APPROVED' AND NEW.approval_status<>'APPROVED' THEN UPDATE image_embeddings SET status='STALE', superseded_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE tenant_id=NEW.tenant_id AND product_image_id=NEW.id AND status='ACTIVE'; END IF; RETURN NEW; END $$")
        op.execute("CREATE TRIGGER trg_stale_image_embedding AFTER UPDATE OF approval_status ON product_images FOR EACH ROW EXECUTE FUNCTION atc_stale_image_embedding()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_stale_image_embedding ON product_images")
        op.execute("DROP FUNCTION IF EXISTS atc_stale_image_embedding")
        op.execute("DROP TRIGGER IF EXISTS trg_guard_active_image_embedding ON image_embeddings")
        op.execute("DROP FUNCTION IF EXISTS atc_guard_active_image_embedding")
    op.drop_table("image_searches")
    op.drop_table("image_embeddings")
    op.drop_table("vision_observations")
