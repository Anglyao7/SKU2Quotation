"""Phase 2 Product Center and Supplier Center core.

Revision ID: 20260718_0003
Revises: 20260718_0002
Requirements: DB-PROD-001, DB-PROD-002, DB-SUP-002
"""
from alembic import op
import sqlalchemy as sa


revision = "20260718_0003"
down_revision = "20260718_0002"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
DEFAULT_ORGANIZATION_ID = "00000000000000000000000000000001"
DEFAULT_TENANT_ID = "00000000000000000000000000000002"
DEFAULT_TENANT = sa.text(f"'{DEFAULT_TENANT_ID}'")
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    _ensure_compatibility_tenant_for_legacy_rows()
    _upgrade_existing_supplier_import_tables()
    _create_product_tables()
    _create_supplier_tables()
    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_rls()


def _ensure_compatibility_tenant_for_legacy_rows() -> None:
    """Create a deterministic migration owner only when pre-tenant MVP rows exist."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "SELECT "
            f"set_config('app.current_organization_id', '{DEFAULT_ORGANIZATION_ID}', true), "
            f"set_config('app.current_tenant_id', '{DEFAULT_TENANT_ID}', true)"
        )
    legacy_rows_exist = (
        "EXISTS (SELECT 1 FROM suppliers) OR "
        "EXISTS (SELECT 1 FROM source_files) OR "
        "EXISTS (SELECT 1 FROM import_jobs) OR "
        "EXISTS (SELECT 1 FROM review_items)"
    )
    op.execute(
        "INSERT INTO organizations "
        "(id, code, name, status, created_at, updated_at, deleted_at) "
        f"SELECT '{DEFAULT_ORGANIZATION_ID}', 'MIGRATED_MVP', "
        "'Migrated MVP Organization', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL "
        f"WHERE ({legacy_rows_exist}) "
        f"AND NOT EXISTS (SELECT 1 FROM organizations WHERE id = '{DEFAULT_ORGANIZATION_ID}')"
    )
    op.execute(
        "INSERT INTO tenants "
        "(id, organization_id, slug, name, default_locale, default_currency, timezone, status, "
        "created_at, updated_at, deleted_at) "
        f"SELECT '{DEFAULT_TENANT_ID}', '{DEFAULT_ORGANIZATION_ID}', 'migrated-mvp', "
        "'Migrated MVP Tenant', 'zh-CN', 'CNY', 'Asia/Shanghai', 'active', "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL "
        f"WHERE ({legacy_rows_exist}) "
        f"AND NOT EXISTS (SELECT 1 FROM tenants WHERE id = '{DEFAULT_TENANT_ID}')"
    )


def _upgrade_existing_supplier_import_tables() -> None:
    with op.batch_alter_table("suppliers", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_index("ix_suppliers_name")
        batch_op.add_column(sa.Column("tenant_id", _uuid(), nullable=False, server_default=DEFAULT_TENANT))
        batch_op.add_column(sa.Column("supplier_code", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("category_summary", sa.String(300), nullable=True))
        batch_op.add_column(sa.Column("country_code", sa.String(2), nullable=True))
        batch_op.add_column(sa.Column("website", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("risk_level", sa.String(30), nullable=False, server_default="UNKNOWN"))
        batch_op.add_column(sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column("name", existing_type=sa.String(200), type_=sa.String(300), nullable=False)
        batch_op.create_foreign_key(
            "fk_suppliers_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint("uq_suppliers_tenant_identity", ["tenant_id", "id"])
        batch_op.create_index("ix_suppliers_name", ["name"], unique=False)
        batch_op.create_index(
            "ix_suppliers_tenant_status_deleted", ["tenant_id", "status", "deleted_at"], unique=False
        )
    op.execute("UPDATE suppliers SET supplier_code = id WHERE supplier_code IS NULL")
    op.execute("UPDATE suppliers SET category_summary = category WHERE category_summary IS NULL")
    op.execute("UPDATE suppliers SET status = UPPER(status)")
    with op.batch_alter_table("suppliers", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.alter_column(
            "tenant_id", existing_type=_uuid(), nullable=False, server_default=None
        )
        batch_op.alter_column(
            "supplier_code", existing_type=sa.String(100), nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_suppliers_tenant_code", ["tenant_id", "supplier_code"]
        )

    with op.batch_alter_table("source_files", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.add_column(sa.Column("tenant_id", _uuid(), nullable=False, server_default=DEFAULT_TENANT))
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW)
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_source_files_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint("uq_source_files_tenant_identity", ["tenant_id", "id"])
    with op.batch_alter_table("source_files", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.alter_column("tenant_id", existing_type=_uuid(), nullable=False, server_default=None)

    with op.batch_alter_table("import_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_import_jobs_source_file_id_source_files", type_="foreignkey")
        batch_op.drop_constraint("fk_import_jobs_supplier_id_suppliers", type_="foreignkey")
        batch_op.add_column(sa.Column("tenant_id", _uuid(), nullable=False, server_default=DEFAULT_TENANT))
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW)
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_import_jobs_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_import_jobs_tenant_source_file",
            "source_files",
            ["tenant_id", "source_file_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_import_jobs_tenant_supplier",
            "suppliers",
            ["tenant_id", "supplier_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint("uq_import_jobs_tenant_identity", ["tenant_id", "id"])
    with op.batch_alter_table("import_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.alter_column("tenant_id", existing_type=_uuid(), nullable=False, server_default=None)

    with op.batch_alter_table("review_items", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_review_items_job_id_import_jobs", type_="foreignkey")
        batch_op.add_column(sa.Column("tenant_id", _uuid(), nullable=False, server_default=DEFAULT_TENANT))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_review_items_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_review_items_tenant_job",
            "import_jobs",
            ["tenant_id", "job_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("uq_review_items_tenant_identity", ["tenant_id", "id"])
    with op.batch_alter_table("review_items", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.alter_column("tenant_id", existing_type=_uuid(), nullable=False, server_default=None)


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def _create_product_tables() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("parent_id", _uuid(), nullable=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')", name="ck_product_categories_status_allowed"),
        sa.CheckConstraint("sort_order >= 0", name="ck_product_categories_sort_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_product_categories_version_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_product_categories_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "parent_id"], ["product_categories.tenant_id", "product_categories.id"], name="fk_product_categories_tenant_parent", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_product_categories"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_categories_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_product_categories_tenant_code"),
    )
    op.create_index("ix_product_categories_tenant_parent_sort", "product_categories", ["tenant_id", "parent_id", "sort_order"])

    op.create_table(
        "products",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_code", sa.String(100), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", _uuid(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("default_unit", sa.String(32), nullable=True),
        sa.Column("current_version", sa.BigInteger(), nullable=False),
        sa.Column("search_document_version", sa.BigInteger(), nullable=False),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("status IN ('DRAFT', 'IN_REVIEW', 'ACTIVE', 'ARCHIVED')", name="ck_products_status_allowed"),
        sa.CheckConstraint("current_version >= 1", name="ck_products_current_version_positive"),
        sa.CheckConstraint("search_document_version >= 0", name="ck_products_search_version_nonnegative"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_products_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "category_id"], ["product_categories.tenant_id", "product_categories.id"], name="fk_products_tenant_category", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_products_created_by_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name="fk_products_updated_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_products_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "product_code", name="uq_products_tenant_code"),
    )
    op.create_index("ix_products_tenant_status_updated", "products", ["tenant_id", "status", "updated_at"])
    op.create_index("ix_products_tenant_category", "products", ["tenant_id", "category_id"])

    op.create_table(
        "product_images",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("storage_provider", sa.String(30), nullable=False),
        sa.Column("bucket", sa.String(100), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("image_role", sa.String(30), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(30), nullable=False),
        sa.Column("alt_text", sa.String(500), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        *_audit_columns(),
        sa.CheckConstraint("byte_size >= 0", name="ck_product_images_byte_size_nonnegative"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="ck_product_images_width_positive"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="ck_product_images_height_positive"),
        sa.CheckConstraint("sort_order >= 0", name="ck_product_images_sort_nonnegative"),
        sa.CheckConstraint("approval_status IN ('SOURCE', 'PENDING', 'APPROVED', 'REJECTED')", name="ck_product_images_approval_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_product_images_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_product_images_tenant_product", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_product_images_created_by_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_product_images"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_images_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "object_key", name="uq_product_images_tenant_object_key"),
    )
    op.create_index("ix_product_images_tenant_product_sort", "product_images", ["tenant_id", "product_id", "sort_order"])

    op.create_table(
        "product_attributes",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("attribute_key", sa.String(100), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Numeric(20, 6), nullable=True),
        sa.Column("unit_code", sa.String(32), nullable=True),
        sa.Column("value_boolean", sa.Boolean(), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("review_status", sa.String(30), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("(CASE WHEN value_text IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_number IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_boolean IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN value_json IS NOT NULL THEN 1 ELSE 0 END) = 1", name="ck_product_attributes_exactly_one_typed_value"),
        sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_product_attributes_confidence_range"),
        sa.CheckConstraint("review_status IN ('AI_SUGGESTED', 'CONFIRMED', 'REJECTED')", name="ck_product_attributes_review_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_product_attributes_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_product_attributes_tenant_product", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_product_attributes"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_attributes_tenant_identity"),
    )
    op.create_index("ix_product_attributes_tenant_product_key", "product_attributes", ["tenant_id", "product_id", "attribute_key"])


def _create_supplier_tables() -> None:
    op.create_table(
        "supplier_products",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("supplier_id", sa.String(40), nullable=False),
        sa.Column("product_id", _uuid(), nullable=False),
        sa.Column("supplier_sku", sa.String(160), nullable=True),
        sa.Column("supplier_product_name", sa.String(500), nullable=True),
        sa.Column("moq", sa.Numeric(20, 6), nullable=True),
        sa.Column("moq_unit", sa.String(32), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        *_audit_columns(),
        sa.CheckConstraint("moq IS NULL OR moq >= 0", name="ck_supplier_products_moq_nonnegative"),
        sa.CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="ck_supplier_products_lead_time_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_supplier_products_version_positive"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'UNVERIFIED')", name="ck_supplier_products_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_supplier_products_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], name="fk_supplier_products_tenant_supplier", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"], name="fk_supplier_products_tenant_product", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_products"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_products_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "supplier_id", "product_id", "supplier_sku", name="uq_supplier_products_tenant_source_sku"),
    )
    op.create_index("ix_supplier_products_tenant_supplier", "supplier_products", ["tenant_id", "supplier_id"])
    op.create_index("ix_supplier_products_tenant_product", "supplier_products", ["tenant_id", "product_id"])
    op.create_index(
        "uq_supplier_products_tenant_null_sku",
        "supplier_products",
        ["tenant_id", "supplier_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("supplier_sku IS NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("supplier_sku IS NULL AND deleted_at IS NULL"),
    )

    score_range_constraints = [
        sa.CheckConstraint(f"{column} IS NULL OR ({column} >= 0 AND {column} <= 100)", name=f"ck_supplier_score_{name}_range")
        for column, name in (
            ("quality_score", "quality"),
            ("price_score", "price"),
            ("delivery_score", "delivery"),
            ("response_score", "response"),
            ("risk_score", "risk"),
            ("overall_score", "overall"),
        )
    ]
    op.create_table(
        "supplier_score",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("supplier_id", sa.String(40), nullable=False),
        sa.Column("quality_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("price_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("delivery_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("response_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("risk_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("overall_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("method_version", sa.String(50), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_summary", sa.JSON(), nullable=True),
        *_audit_columns(),
        *score_range_constraints,
        sa.CheckConstraint("sample_size >= 0", name="ck_supplier_score_sample_size_nonnegative"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_supplier_score_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], name="fk_supplier_score_tenant_supplier", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_score"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_supplier_score_tenant_identity"),
    )
    op.create_index("ix_supplier_score_tenant_supplier_calculated", "supplier_score", ["tenant_id", "supplier_id", "calculated_at"])


def _enable_postgresql_rls() -> None:
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    for table in (
        "product_categories",
        "products",
        "product_images",
        "product_attributes",
        "suppliers",
        "supplier_products",
        "supplier_score",
        "source_files",
        "import_jobs",
        "review_items",
    ):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING (tenant_id = {tenant_id}) WITH CHECK (tenant_id = {tenant_id})'
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "review_items", "import_jobs", "source_files", "supplier_score", "supplier_products",
            "suppliers", "product_attributes", "product_images", "products", "product_categories",
        ):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')

    op.drop_table("supplier_score")
    op.drop_table("supplier_products")
    op.drop_table("product_attributes")
    op.drop_table("product_images")
    op.drop_table("products")
    op.drop_table("product_categories")
    _downgrade_existing_supplier_import_tables()


def _downgrade_existing_supplier_import_tables() -> None:
    with op.batch_alter_table("review_items", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_review_items_tenant_job", type_="foreignkey")
        batch_op.drop_constraint("fk_review_items_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_constraint("uq_review_items_tenant_identity", type_="unique")
        batch_op.create_foreign_key(
            "fk_review_items_job_id_import_jobs", "import_jobs", ["job_id"], ["id"]
        )
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("import_jobs", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_import_jobs_tenant_source_file", type_="foreignkey")
        batch_op.drop_constraint("fk_import_jobs_tenant_supplier", type_="foreignkey")
        batch_op.drop_constraint("fk_import_jobs_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_constraint("uq_import_jobs_tenant_identity", type_="unique")
        batch_op.create_foreign_key(
            "fk_import_jobs_source_file_id_source_files", "source_files", ["source_file_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_import_jobs_supplier_id_suppliers", "suppliers", ["supplier_id"], ["id"]
        )
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("source_files", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("fk_source_files_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_constraint("uq_source_files_tenant_identity", type_="unique")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("tenant_id")

    op.execute("UPDATE suppliers SET status = LOWER(status)")
    with op.batch_alter_table("suppliers", naming_convention=NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint("uq_suppliers_tenant_code", type_="unique")
        batch_op.drop_constraint("uq_suppliers_tenant_identity", type_="unique")
        batch_op.drop_constraint("fk_suppliers_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_index("ix_suppliers_tenant_status_deleted")
        batch_op.drop_index("ix_suppliers_name")
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("version")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("website")
        batch_op.drop_column("country_code")
        batch_op.drop_column("category_summary")
        batch_op.drop_column("supplier_code")
        batch_op.drop_column("tenant_id")
        batch_op.alter_column("name", existing_type=sa.String(300), type_=sa.String(200), nullable=False)
        batch_op.create_index("ix_suppliers_name", ["name"], unique=True)
