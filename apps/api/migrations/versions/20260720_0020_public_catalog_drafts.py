"""Add public catalog projection and human-gated quote drafts.

Revision ID: 20260720_0020
Revises: 20260718_0019
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_0020"
down_revision = "20260718_0019"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
U = lambda: sa.Uuid(as_uuid=True)


def audit() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"], ["tenants.id"], name=name, ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "tenant_public_profiles",
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(1000), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("contact_phone", sa.String(80), nullable=True),
        sa.Column("publication_status", sa.String(20), nullable=False),
        *audit(),
        sa.CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'SUSPENDED')",
            name="ck_tenant_public_profiles_publication_status_allowed",
        ),
        tenant_fk("fk_tenant_public_profiles_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_public_profiles"),
        sa.UniqueConstraint("slug", name="uq_tenant_public_profiles_slug"),
    )
    op.create_index(
        "ix_tenant_public_profiles_publication_slug",
        "tenant_public_profiles",
        ["publication_status", "slug"],
    )

    op.create_table(
        "public_catalog_offers",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("tags", JSON, nullable=False),
        sa.Column("publication_status", sa.String(20), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *audit(),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_public_catalog_offers_unit_price_nonnegative"
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_public_catalog_offers_currency_format",
        ),
        sa.CheckConstraint(
            "publication_status IN ('DRAFT', 'PUBLISHED', 'SUSPENDED')",
            name="ck_public_catalog_offers_publication_status_allowed",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_public_catalog_offers_validity_range_valid",
        ),
        tenant_fk("fk_public_catalog_offers_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_public_catalog_offers_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_public_catalog_offers"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_public_catalog_offers_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id", "sku_id", name="uq_public_catalog_offers_tenant_sku"
        ),
    )
    op.create_index(
        "ix_public_catalog_offers_tenant_publication",
        "public_catalog_offers",
        ["tenant_id", "publication_status"],
    )

    op.create_table(
        "public_quote_drafts",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("request_number", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_company", sa.String(200), nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_phone", sa.String(80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("estimated_total", sa.Numeric(20, 2), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", JSON, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("disclaimer_version", sa.String(40), nullable=False),
        *audit(),
        sa.CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED', 'EXPIRED')",
            name="ck_public_quote_drafts_status_allowed",
        ),
        sa.CheckConstraint(
            "subtotal_amount >= 0", name="ck_public_quote_drafts_subtotal_nonnegative"
        ),
        sa.CheckConstraint(
            "estimated_total >= 0",
            name="ck_public_quote_drafts_estimated_total_nonnegative",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_public_quote_drafts_content_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_public_quote_drafts_currency_format",
        ),
        tenant_fk("fk_public_quote_drafts_tenant_id_tenants"),
        sa.PrimaryKeyConstraint("id", name="pk_public_quote_drafts"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_public_quote_drafts_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "request_number",
            name="uq_public_quote_drafts_tenant_number",
        ),
    )
    op.create_index(
        "ix_public_quote_drafts_tenant_status_created",
        "public_quote_drafts",
        ["tenant_id", "status", "created_at"],
    )

    op.create_table(
        "public_quote_draft_items",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("quote_draft_id", U(), nullable=False),
        sa.Column("sku_id", U(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("product_id_snapshot", U(), nullable=False),
        sa.Column("product_version", sa.BigInteger(), nullable=False),
        sa.Column("sku_version", sa.BigInteger(), nullable=False),
        sa.Column("sku_code_snapshot", sa.String(160), nullable=False),
        sa.Column("name_snapshot", sa.String(500), nullable=False),
        sa.Column("description_snapshot", sa.Text(), nullable=True),
        sa.Column("category_snapshot", sa.String(200), nullable=True),
        sa.Column("tags_snapshot", JSON, nullable=False),
        sa.Column("image_url_snapshot", sa.String(2000), nullable=True),
        sa.Column("minimum_order_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("unit_code_snapshot", sa.String(32), nullable=False),
        sa.Column("currency_snapshot", sa.String(3), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(20, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(20, 2), nullable=False),
        *audit(),
        sa.CheckConstraint(
            "position >= 1", name="ck_public_quote_draft_items_position_positive"
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_public_quote_draft_items_quantity_positive"
        ),
        sa.CheckConstraint(
            "minimum_order_quantity > 0",
            name="ck_public_quote_draft_items_moq_positive",
        ),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0",
            name="ck_public_quote_draft_items_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "line_total >= 0", name="ck_public_quote_draft_items_line_total_nonnegative"
        ),
        sa.CheckConstraint(
            "product_version >= 1",
            name="ck_public_quote_draft_items_product_version_positive",
        ),
        sa.CheckConstraint(
            "sku_version >= 1", name="ck_public_quote_draft_items_sku_version_positive"
        ),
        tenant_fk("fk_public_quote_draft_items_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_draft_id"],
            ["public_quote_drafts.tenant_id", "public_quote_drafts.id"],
            name="fk_public_quote_draft_items_tenant_draft",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_public_quote_draft_items_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_public_quote_draft_items"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_public_quote_draft_items_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "quote_draft_id",
            "position",
            name="uq_public_quote_draft_items_position",
        ),
    )
    op.create_index(
        "ix_public_quote_draft_items_tenant_draft",
        "public_quote_draft_items",
        ["tenant_id", "quote_draft_id"],
    )

    op.create_table(
        "public_quote_download_tokens",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("quote_draft_id", U(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("one_time", sa.Boolean(), nullable=False),
        *audit(),
        sa.CheckConstraint(
            "length(token_hash) = 64",
            name="ck_public_quote_download_tokens_token_hash_sha256_length",
        ),
        tenant_fk("fk_public_quote_download_tokens_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_draft_id"],
            ["public_quote_drafts.tenant_id", "public_quote_drafts.id"],
            name="fk_public_quote_download_tokens_tenant_draft",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_public_quote_download_tokens"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_public_quote_download_tokens_tenant_identity",
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_public_quote_download_tokens_hash"
        ),
    )
    op.create_index(
        "ix_public_quote_download_tokens_tenant_draft_expiry",
        "public_quote_download_tokens",
        ["tenant_id", "quote_draft_id", "expires_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "tenant_public_profiles" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "tenant_public_profiles" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "tenant_public_profiles_published_read" '
            'ON "tenant_public_profiles" FOR SELECT '
            "USING (publication_status = 'PUBLISHED' AND deleted_at IS NULL)"
        )
        op.execute(
            'CREATE POLICY "tenant_public_profiles_tenant_write" '
            'ON "tenant_public_profiles" FOR ALL '
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )
        for table in (
            "public_catalog_offers",
            "public_quote_drafts",
            "public_quote_draft_items",
            "public_quote_download_tokens",
        ):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
            op.execute(
                f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
                f"FOR ALL USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
            )
        op.execute(
            "CREATE FUNCTION atc_reject_public_quote_draft_item_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "RAISE EXCEPTION 'public quote draft item snapshots are immutable'; END $$"
        )
        op.execute(
            "CREATE TRIGGER trg_immutable_public_quote_draft_items "
            "BEFORE UPDATE OR DELETE ON public_quote_draft_items FOR EACH ROW "
            "EXECUTE FUNCTION atc_reject_public_quote_draft_item_mutation()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_immutable_public_quote_draft_items "
            "ON public_quote_draft_items"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS atc_reject_public_quote_draft_item_mutation"
        )
    op.drop_index(
        "ix_public_quote_download_tokens_tenant_draft_expiry",
        table_name="public_quote_download_tokens",
    )
    op.drop_table("public_quote_download_tokens")
    op.drop_index(
        "ix_public_quote_draft_items_tenant_draft",
        table_name="public_quote_draft_items",
    )
    op.drop_table("public_quote_draft_items")
    op.drop_index(
        "ix_public_quote_drafts_tenant_status_created",
        table_name="public_quote_drafts",
    )
    op.drop_table("public_quote_drafts")
    op.drop_index(
        "ix_public_catalog_offers_tenant_publication",
        table_name="public_catalog_offers",
    )
    op.drop_table("public_catalog_offers")
    op.drop_index(
        "ix_tenant_public_profiles_publication_slug",
        table_name="tenant_public_profiles",
    )
    op.drop_table("tenant_public_profiles")
