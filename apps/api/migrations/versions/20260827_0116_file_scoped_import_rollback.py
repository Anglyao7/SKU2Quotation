"""Track immutable product and SKU provenance for file-scoped rollback.

Revision ID: 20260827_0116
Revises: 20260827_0115
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260827_0116"
down_revision = "20260827_0115"
branch_labels = None
depends_on = None


def _add_columns_and_indexes() -> None:
    op.add_column(
        "products",
        sa.Column("origin_source_file_id", sa.String(40), nullable=True),
    )
    op.create_index(
        "ix_products_tenant_origin_source_file",
        "products",
        ["tenant_id", "origin_source_file_id"],
    )
    op.add_column(
        "skus",
        sa.Column("origin_source_file_id", sa.String(40), nullable=True),
    )
    op.create_index(
        "ix_skus_tenant_origin_source_file",
        "skus",
        ["tenant_id", "origin_source_file_id"],
    )
    op.add_column(
        "import_jobs",
        sa.Column("file_rollback_at", sa.DateTime(timezone=True), nullable=True),
    )


def _add_postgres_foreign_keys() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    with op.batch_alter_table("products") as batch:
        batch.create_foreign_key(
            "fk_products_tenant_origin_source_file",
            "source_files",
            ["tenant_id", "origin_source_file_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("skus") as batch:
        batch.create_foreign_key(
            "fk_skus_tenant_origin_source_file",
            "source_files",
            ["tenant_id", "origin_source_file_id"],
            ["tenant_id", "id"],
            ondelete="RESTRICT",
        )


def _backfill_direct_sku_provenance() -> None:
    # ``latest_import_job_id`` is only proof of origin when the SKU itself was
    # created during that job. Some legacy async jobs recorded ``completed_at``
    # shortly before the catalog transaction became visible, so use the same
    # narrow compatibility window as the Product-only backfill. Rows created
    # before the import and merely updated by it remain NULL.
    bind = op.get_bind()
    completed_window = (
        "skus.created_at <= jobs.completed_at + INTERVAL '10 minutes'"
        if bind.dialect.name == "postgresql"
        else "skus.created_at <= datetime(jobs.completed_at, '+10 minutes')"
    )
    op.execute(
        sa.text(
            f"""
            UPDATE skus
               SET origin_source_file_id = (
                   SELECT jobs.source_file_id
                     FROM import_jobs AS jobs
                    WHERE jobs.tenant_id = skus.tenant_id
                      AND jobs.id = skus.latest_import_job_id
                      AND jobs.source_type = 'PRODUCT_TEMPLATE'
                      AND jobs.status = 'published'
                      AND skus.created_at >= jobs.created_at
                      AND (jobs.completed_at IS NULL OR {completed_window})
               )
             WHERE origin_source_file_id IS NULL
               AND latest_import_job_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM import_jobs AS jobs
                    WHERE jobs.tenant_id = skus.tenant_id
                      AND jobs.id = skus.latest_import_job_id
                      AND jobs.source_type = 'PRODUCT_TEMPLATE'
                      AND jobs.status = 'published'
                      AND skus.created_at >= jobs.created_at
                      AND (jobs.completed_at IS NULL OR {completed_window})
               )
            """
        )
    )


def _backfill_products_from_skus() -> None:
    # A product can inherit a source only when all attributed child SKUs agree
    # on one file *and* the Product itself was created during that file's
    # import. This avoids archiving an older Product that the file only added
    # SKUs to.
    bind = op.get_bind()
    completed_window = (
        "products.created_at <= jobs.completed_at + INTERVAL '10 minutes'"
        if bind.dialect.name == "postgresql"
        else "products.created_at <= datetime(jobs.completed_at, '+10 minutes')"
    )
    # Materialize the small candidate set once. Repeating the grouped child-SKU
    # lookup as a correlated subquery for every Product is prohibitively slow
    # for larger SQLite catalogs.
    candidate_table = "migration_0116_products_from_skus"
    op.execute(sa.text(f"DROP TABLE IF EXISTS {candidate_table}"))
    op.execute(
        sa.text(
            f"""
            CREATE TEMPORARY TABLE {candidate_table} AS
            SELECT products.tenant_id AS tenant_id,
                   products.id AS product_id,
                   MIN(skus.origin_source_file_id) AS source_file_id
              FROM products
              JOIN skus
                ON skus.tenant_id = products.tenant_id
               AND skus.product_id = products.id
               AND skus.origin_source_file_id IS NOT NULL
              JOIN import_jobs AS jobs
                ON jobs.tenant_id = skus.tenant_id
               AND jobs.source_file_id = skus.origin_source_file_id
              LEFT JOIN catalog_import_batches AS batches
                ON batches.tenant_id = jobs.tenant_id
               AND batches.id = jobs.batch_id
             WHERE products.origin_source_file_id IS NULL
               AND jobs.source_type = 'PRODUCT_TEMPLATE'
               AND jobs.status = 'published'
               AND products.created_at >= jobs.created_at
               AND (jobs.completed_at IS NULL OR {completed_window})
               AND (
                   jobs.batch_id IS NULL
                   OR batches.created_by_user_id = products.created_by
               )
             GROUP BY products.tenant_id, products.id
            HAVING COUNT(DISTINCT skus.origin_source_file_id) = 1
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE UNIQUE INDEX migration_0116_products_from_skus_lookup
                ON {candidate_table} (tenant_id, product_id)
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE products
               SET origin_source_file_id = (
                   SELECT candidates.source_file_id
                     FROM {candidate_table} AS candidates
                    WHERE candidates.tenant_id = products.tenant_id
                      AND candidates.product_id = products.id
               )
             WHERE origin_source_file_id IS NULL
               AND EXISTS (
                   SELECT 1
                     FROM {candidate_table} AS candidates
                    WHERE candidates.tenant_id = products.tenant_id
                      AND candidates.product_id = products.id
               )
            """
        )
    )
    op.execute(sa.text(f"DROP TABLE {candidate_table}"))


def _backfill_uniquely_timed_batch_products() -> None:
    # Early product-only imports created Product rows before generated base
    # SKUs gained import provenance. Some legacy asynchronous jobs wrote
    # ``completed_at`` a few seconds before the catalog transaction became
    # visible, so allow a small compatibility window. A product is still
    # backfilled only when exactly one published, batch-owned file from the
    # same actor matches, leaving ambiguous history untouched.
    bind = op.get_bind()
    completed_window = (
        "products.created_at <= jobs.completed_at + INTERVAL '10 minutes'"
        if bind.dialect.name == "postgresql"
        else "products.created_at <= datetime(jobs.completed_at, '+10 minutes')"
    )
    op.execute(
        sa.text(
            f"""
            UPDATE products
               SET origin_source_file_id = (
                   SELECT MIN(jobs.source_file_id)
                     FROM import_jobs AS jobs
                     JOIN catalog_import_batches AS batches
                       ON batches.tenant_id = jobs.tenant_id
                      AND batches.id = jobs.batch_id
                    WHERE jobs.tenant_id = products.tenant_id
                      AND jobs.source_type = 'PRODUCT_TEMPLATE'
                      AND jobs.status = 'published'
                      AND batches.created_by_user_id = products.created_by
                      AND products.created_at >= jobs.created_at
                      AND jobs.completed_at IS NOT NULL
                      AND {completed_window}
               )
             WHERE origin_source_file_id IS NULL
               AND 1 = (
                   SELECT COUNT(DISTINCT jobs.source_file_id)
                     FROM import_jobs AS jobs
                     JOIN catalog_import_batches AS batches
                       ON batches.tenant_id = jobs.tenant_id
                      AND batches.id = jobs.batch_id
                    WHERE jobs.tenant_id = products.tenant_id
                      AND jobs.source_type = 'PRODUCT_TEMPLATE'
                      AND jobs.status = 'published'
                      AND batches.created_by_user_id = products.created_by
                      AND products.created_at >= jobs.created_at
                      AND jobs.completed_at IS NOT NULL
                      AND {completed_window}
               )
            """
        )
    )


def _backfill_generated_base_skus() -> None:
    bind = op.get_bind()
    marker_predicate = (
        "COALESCE(skus.option_values -> '_sku2quotation' ->> 'base_product', 'false') = 'true'"
        if bind.dialect.name == "postgresql"
        else "COALESCE(json_extract(skus.option_values, '$._sku2quotation.base_product'), 0) = 1"
    )
    op.execute(
        sa.text(
            f"""
            UPDATE skus
               SET origin_source_file_id = (
                   SELECT products.origin_source_file_id
                     FROM products
                    WHERE products.tenant_id = skus.tenant_id
                      AND products.id = skus.product_id
               )
             WHERE origin_source_file_id IS NULL
               AND {marker_predicate}
               AND EXISTS (
                   SELECT 1
                     FROM products
                    WHERE products.tenant_id = skus.tenant_id
                      AND products.id = skus.product_id
                      AND products.origin_source_file_id IS NOT NULL
               )
            """
        )
    )


def upgrade() -> None:
    _add_columns_and_indexes()
    _add_postgres_foreign_keys()
    _backfill_direct_sku_provenance()
    _backfill_products_from_skus()
    _backfill_uniquely_timed_batch_products()
    _backfill_generated_base_skus()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.batch_alter_table("skus") as batch:
            batch.drop_constraint(
                "fk_skus_tenant_origin_source_file",
                type_="foreignkey",
            )
        with op.batch_alter_table("products") as batch:
            batch.drop_constraint(
                "fk_products_tenant_origin_source_file",
                type_="foreignkey",
            )
    op.drop_column("import_jobs", "file_rollback_at")
    op.drop_index("ix_skus_tenant_origin_source_file", table_name="skus")
    op.drop_column("skus", "origin_source_file_id")
    op.drop_index("ix_products_tenant_origin_source_file", table_name="products")
    op.drop_column("products", "origin_source_file_id")
