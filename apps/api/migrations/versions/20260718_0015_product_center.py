"""Add Product Center SKU, category attributes, price history and audit facts.

Revision ID: 20260718_0015
Revises: 20260718_0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_0015"
down_revision = "20260718_0014"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(none_as_null=True), "postgresql")
NOW = sa.text("CURRENT_TIMESTAMP")


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _create_skus() -> None:
    op.create_table(
        "skus",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("sku_code", sa.String(160), nullable=False),
        sa.Column("name", sa.String(500), nullable=True),
        sa.Column("option_values", JSON_DOCUMENT, nullable=False),
        sa.Column("barcode", sa.String(120), nullable=True),
        sa.Column("default_moq", sa.Numeric(20, 6), nullable=True),
        sa.Column("moq_unit", sa.String(32), nullable=True),
        sa.Column("weight", sa.Numeric(20, 6), nullable=True),
        sa.Column("weight_unit", sa.String(32), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="DRAFT"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", _uuid(), nullable=True),
        sa.Column("updated_by_user_id", _uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'INACTIVE', 'ARCHIVED')",
            name="ck_skus_status_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="ck_skus_version_positive"),
        sa.CheckConstraint(
            "default_moq IS NULL OR default_moq >= 0", name="ck_skus_moq_nonnegative"
        ),
        sa.CheckConstraint("weight IS NULL OR weight >= 0", name="ck_skus_weight_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_skus_tenant_id_tenants", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_skus_tenant_product",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name="fk_skus_created_by_user", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], name="fk_skus_updated_by_user", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_skus"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_skus_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "sku_code", name="uq_skus_tenant_code"),
    )
    op.create_index(
        "ix_skus_tenant_product_status", "skus", ["tenant_id", "product_id", "status"]
    )


def _create_attribute_definitions() -> None:
    op.create_table(
        "attribute_definitions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("category_id", _uuid(), nullable=True),
        sa.Column("attribute_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(20), nullable=False),
        sa.Column("unit_code", sa.String(32), nullable=True),
        sa.Column("enum_values", JSON_DOCUMENT, nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_variant", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_filterable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_matchable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        *_audit_columns(),
        sa.CheckConstraint(
            "data_type IN ('TEXT', 'NUMBER', 'BOOLEAN', 'ENUM')",
            name="ck_attribute_definitions_data_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')", name="ck_attribute_definitions_status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="ck_attribute_definitions_version_positive"),
        sa.CheckConstraint(
            "(data_type = 'ENUM' AND enum_values IS NOT NULL) OR data_type <> 'ENUM'",
            name="ck_attribute_definitions_enum_values_required",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_attribute_definitions_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category_id"],
            ["product_categories.tenant_id", "product_categories.id"],
            name="fk_attribute_definitions_tenant_category",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_attribute_definitions"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_attribute_definitions_tenant_identity"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "category_id",
            "attribute_key",
            name="uq_attribute_definitions_category_key",
        ),
    )
    op.create_index(
        "uq_attribute_definitions_global_key",
        "attribute_definitions",
        ["tenant_id", "attribute_key"],
        unique=True,
        postgresql_where=sa.text("category_id IS NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("category_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_attribute_definitions_tenant_category_status",
        "attribute_definitions",
        ["tenant_id", "category_id", "status"],
    )


def _extend_existing_product_tables() -> None:
    with op.batch_alter_table("product_attributes") as batch:
        batch.add_column(sa.Column("attribute_definition_id", _uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_product_attributes_tenant_definition",
            "attribute_definitions",
            ["tenant_id", "attribute_definition_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("supplier_products") as batch:
        batch.add_column(sa.Column("sku_id", _uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_supplier_products_tenant_sku",
            "skus",
            ["tenant_id", "sku_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_supplier_products_tenant_sku", ["tenant_id", "sku_id"])


def _create_supplier_prices() -> None:
    op.create_table(
        "supplier_prices",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("supplier_product_id", _uuid(), nullable=False),
        sa.Column("sku_id", _uuid(), nullable=True),
        sa.Column("min_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("max_quantity", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_code", sa.String(32), nullable=False),
        sa.Column("incoterm", sa.String(20), nullable=True),
        sa.Column("tax_status", sa.String(40), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="CONFIRMED"),
        sa.Column("source_evidence_id", _uuid(), nullable=True),
        sa.Column("confirmed_by_membership_id", _uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_price_id", _uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint(
            "min_quantity >= 0", name="ck_supplier_prices_min_quantity_nonnegative"
        ),
        sa.CheckConstraint(
            "max_quantity IS NULL OR max_quantity >= min_quantity",
            name="ck_supplier_prices_quantity_range_valid",
        ),
        sa.CheckConstraint("unit_price >= 0", name="ck_supplier_prices_unit_price_nonnegative"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_supplier_prices_currency_format",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_supplier_prices_validity_range_valid",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'SUPERSEDED', 'REVOKED')",
            name="ck_supplier_prices_status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'CONFIRMED' AND confirmed_by_membership_id IS NOT NULL "
            "AND confirmed_at IS NOT NULL) OR status <> 'CONFIRMED'",
            name="ck_supplier_prices_confirmation_required",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_supplier_prices_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supplier_product_id"],
            ["supplier_products.tenant_id", "supplier_products.id"],
            name="fk_supplier_prices_tenant_supplier_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sku_id"],
            ["skus.tenant_id", "skus.id"],
            name="fk_supplier_prices_tenant_sku",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_evidence_id"],
            ["ai_source_evidence.tenant_id", "ai_source_evidence.id"],
            name="fk_supplier_prices_tenant_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_supplier_prices_tenant_confirmer",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_price_id"],
            ["supplier_prices.tenant_id", "supplier_prices.id"],
            name="fk_supplier_prices_tenant_superseded_price",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_prices"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_prices_tenant_identity"),
    )
    op.create_index(
        "ix_supplier_prices_tenant_source_validity",
        "supplier_prices",
        ["tenant_id", "supplier_product_id", "status", "valid_from"],
    )
    op.create_index(
        "ix_supplier_prices_tenant_sku", "supplier_prices", ["tenant_id", "sku_id"]
    )


def _create_product_audit_events() -> None:
    op.create_table(
        "product_audit_events",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("before", JSON_DOCUMENT, nullable=False),
        sa.Column("after", JSON_DOCUMENT, nullable=False),
        sa.Column("actor_membership_id", _uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        *_audit_columns(),
        sa.CheckConstraint(
            "entity_type IN ('PRODUCT', 'SKU', 'PRICE', 'CATEGORY', "
            "'ATTRIBUTE_DEFINITION', 'CANDIDATE_REVIEW')",
            name="ck_product_audit_events_entity_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_product_audit_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["products.tenant_id", "products.id"],
            name="fk_product_audit_events_tenant_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_product_audit_events_tenant_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_audit_events"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_product_audit_events_tenant_identity"
        ),
    )
    op.create_index(
        "ix_product_audit_events_tenant_product_time",
        "product_audit_events",
        ["tenant_id", "product_id", "occurred_at"],
    )


def _enable_rls() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    tenant = "nullif(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in (
        "skus",
        "attribute_definitions",
        "supplier_prices",
        "product_audit_events",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )


def upgrade() -> None:
    _create_skus()
    _create_attribute_definitions()
    _extend_existing_product_tables()
    _create_supplier_prices()
    _create_product_audit_events()
    _enable_rls()


def downgrade() -> None:
    op.drop_index(
        "ix_product_audit_events_tenant_product_time", table_name="product_audit_events"
    )
    op.drop_table("product_audit_events")
    op.drop_index("ix_supplier_prices_tenant_sku", table_name="supplier_prices")
    op.drop_index(
        "ix_supplier_prices_tenant_source_validity", table_name="supplier_prices"
    )
    op.drop_table("supplier_prices")
    with op.batch_alter_table("supplier_products") as batch:
        batch.drop_index("ix_supplier_products_tenant_sku")
        batch.drop_constraint("fk_supplier_products_tenant_sku", type_="foreignkey")
        batch.drop_column("sku_id")
    with op.batch_alter_table("product_attributes") as batch:
        batch.drop_constraint("fk_product_attributes_tenant_definition", type_="foreignkey")
        batch.drop_column("attribute_definition_id")
    op.drop_index(
        "ix_attribute_definitions_tenant_category_status",
        table_name="attribute_definitions",
    )
    op.drop_index(
        "uq_attribute_definitions_global_key", table_name="attribute_definitions"
    )
    op.drop_table("attribute_definitions")
    op.drop_index("ix_skus_tenant_product_status", table_name="skus")
    op.drop_table("skus")
