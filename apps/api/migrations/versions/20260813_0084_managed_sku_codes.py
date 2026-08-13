"""Add merchant-readable managed SKU codes and backfill existing catalogs.

Revision ID: 20260813_0084
Revises: 20260813_0083
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op


revision = "20260813_0084"
down_revision = "20260813_0083"
branch_labels = None
depends_on = None


def _prefix(name: str, slug: str) -> str:
    normalized_name = unicodedata.normalize("NFKC", name or "")
    english = "".join(re.findall(r"[A-Za-z0-9]", normalized_name)).upper()
    if english:
        return english[:4].ljust(4, "X")
    normalized_slug = unicodedata.normalize("NFKC", slug or "")
    slug_ascii = "".join(re.findall(r"[A-Za-z0-9]", normalized_slug)).upper()
    return (slug_ascii or "SHOP")[:4].ljust(4, "X")


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        result = datetime.now(UTC)
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


def _business_date(value: object, timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        timezone = ZoneInfo("UTC")
    return _datetime(value).astimezone(timezone).date()


def _format_code(
    prefix: str,
    product_date: date,
    product_sequence: int,
    sku_sequence: int,
) -> str:
    return (
        f"{prefix}-{product_date:%y%m%d}{product_sequence:03d}-"
        f"{sku_sequence:03d}"
    )


def _backfill_postgresql() -> None:
    """Use set-based SQL for production-sized PostgreSQL catalogs.

    These statements also render in Alembic's offline SQL artifact, so the
    release bundle contains the same data migration that runs in production.
    """

    op.execute(
        sa.text(
            """
            UPDATE tenants
            SET sku_prefix = rpad(
                substring(
                    COALESCE(
                        NULLIF(upper(regexp_replace(name, '[^A-Za-z0-9]', '', 'g')), ''),
                        NULLIF(upper(regexp_replace(slug, '[^A-Za-z0-9]', '', 'g')), ''),
                        'SHOP'
                    )
                    FROM 1 FOR 4
                ),
                4,
                'X'
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH dated_products AS (
                SELECT
                    products.id,
                    products.tenant_id,
                    products.created_at,
                    (products.created_at AT TIME ZONE
                        COALESCE(NULLIF(tenants.timezone, ''), 'UTC'))::date
                        AS code_date
                FROM products
                JOIN tenants ON tenants.id = products.tenant_id
            ),
            numbered_products AS (
                SELECT
                    id,
                    code_date,
                    row_number() OVER (
                        PARTITION BY tenant_id, code_date
                        ORDER BY created_at, id
                    )::integer AS code_sequence
                FROM dated_products
            )
            UPDATE products
            SET
                sku_code_date = numbered_products.code_date,
                sku_code_sequence = numbered_products.code_sequence
            FROM numbered_products
            WHERE products.id = numbered_products.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM skus
                    GROUP BY tenant_id, product_id
                    HAVING count(*) > 999
                ) THEN
                    RAISE EXCEPTION
                        'managed SKU migration supports at most 999 variants per product';
                END IF;
            END
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH numbered_skus AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY tenant_id, product_id
                        ORDER BY created_at, id
                    )::integer AS variant_sequence
                FROM skus
            )
            UPDATE skus
            SET
                source_sku_code = skus.sku_code,
                sku_code = 'MIG-' || upper(replace(skus.id::text, '-', '')),
                sku_sequence = numbered_skus.variant_sequence
            FROM numbered_skus
            WHERE skus.id = numbered_skus.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE skus
            SET sku_code =
                tenants.sku_prefix || '-' ||
                to_char(products.sku_code_date, 'YYMMDD') ||
                CASE
                    WHEN products.sku_code_sequence < 1000
                    THEN lpad(products.sku_code_sequence::text, 3, '0')
                    ELSE products.sku_code_sequence::text
                END || '-' ||
                lpad(skus.sku_sequence::text, 3, '0')
            FROM products, tenants
            WHERE
                skus.product_id = products.id
                AND skus.tenant_id = products.tenant_id
                AND tenants.id = skus.tenant_id
            """
        )
    )


def _backfill_rows() -> None:
    bind = op.get_bind()
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("timezone", sa.String()),
        sa.column("sku_prefix", sa.String()),
    )
    products = sa.table(
        "products",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("sku_code_date", sa.Date()),
        sa.column("sku_code_sequence", sa.Integer()),
    )
    skus = sa.table(
        "skus",
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("product_id", sa.Uuid()),
        sa.column("sku_code", sa.String()),
        sa.column("source_sku_code", sa.String()),
        sa.column("sku_sequence", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    for tenant in bind.execute(
        sa.select(
            tenants.c.id,
            tenants.c.name,
            tenants.c.slug,
            tenants.c.timezone,
        ).order_by(tenants.c.id)
    ).mappings():
        tenant_prefix = _prefix(
            str(tenant["name"] or ""),
            str(tenant["slug"] or ""),
        )
        bind.execute(
            tenants.update()
            .where(tenants.c.id == tenant["id"])
            .values(sku_prefix=tenant_prefix)
        )
        product_rows = list(
            bind.execute(
                sa.select(
                    products.c.id,
                    products.c.created_at,
                )
                .where(products.c.tenant_id == tenant["id"])
                .order_by(products.c.created_at, products.c.id)
            ).mappings()
        )
        daily_sequence: dict[date, int] = defaultdict(int)
        product_identity: dict[object, tuple[date, int]] = {}
        for product in product_rows:
            product_date = _business_date(
                product.created_at,
                str(tenant["timezone"] or "UTC"),
            )
            daily_sequence[product_date] += 1
            product_sequence = daily_sequence[product_date]
            product_identity[product.id] = (product_date, product_sequence)
            bind.execute(
                products.update()
                .where(products.c.id == product.id)
                .values(
                    sku_code_date=product_date,
                    sku_code_sequence=product_sequence,
                )
            )

        sku_rows = list(
            bind.execute(
                sa.select(
                    skus.c.id,
                    skus.c.product_id,
                    skus.c.sku_code,
                    skus.c.created_at,
                )
                .where(skus.c.tenant_id == tenant.id)
                .order_by(skus.c.product_id, skus.c.created_at, skus.c.id)
            ).mappings()
        )
        sku_sequence_by_product: dict[object, int] = defaultdict(int)
        final_codes: list[tuple[object, str, int]] = []
        for sku in sku_rows:
            product_date, product_sequence = product_identity[sku.product_id]
            sku_sequence_by_product[sku.product_id] += 1
            sku_sequence = sku_sequence_by_product[sku.product_id]
            if sku_sequence > 999:
                raise RuntimeError(
                    "managed SKU migration supports at most 999 variants per product"
                )
            final_code = _format_code(
                tenant_prefix,
                product_date,
                product_sequence,
                sku_sequence,
            )
            final_codes.append((sku.id, final_code, sku_sequence))
            # Move every old value out of the unique namespace first so a
            # historical code equal to a future generated code cannot collide.
            bind.execute(
                skus.update()
                .where(skus.c.id == sku.id)
                .values(
                    source_sku_code=sku.sku_code,
                    sku_code=f"MIG-{str(sku.id).replace('-', '').upper()}",
                    sku_sequence=sku_sequence,
                )
            )
        for sku_id, final_code, sku_sequence in final_codes:
            bind.execute(
                skus.update()
                .where(skus.c.id == sku_id)
                .values(sku_code=final_code, sku_sequence=sku_sequence)
            )


def _backfill() -> None:
    if op.get_context().dialect.name == "postgresql":
        _backfill_postgresql()
        return
    _backfill_rows()


def _restore_source_codes_postgresql() -> None:
    op.execute(
        sa.text(
            """
            CREATE TEMPORARY TABLE atc_sku_code_downgrade AS
            SELECT
                id,
                COALESCE(NULLIF(source_sku_code, ''), sku_code) AS target_code
            FROM skus
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE skus
            SET sku_code = 'DOWN-' || upper(replace(id::text, '-', ''))
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE skus
            SET sku_code = atc_sku_code_downgrade.target_code
            FROM atc_sku_code_downgrade
            WHERE skus.id = atc_sku_code_downgrade.id
            """
        )
    )
    op.execute(sa.text("DROP TABLE atc_sku_code_downgrade"))


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "sku_prefix",
            sa.String(length=4),
            nullable=False,
            server_default="SHOP",
        ),
    )
    op.add_column("products", sa.Column("sku_code_date", sa.Date(), nullable=True))
    op.add_column(
        "products",
        sa.Column("sku_code_sequence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "skus",
        sa.Column("source_sku_code", sa.String(length=160), nullable=True),
    )
    op.add_column("skus", sa.Column("sku_sequence", sa.Integer(), nullable=True))
    _backfill()
    op.create_index(
        "uq_products_tenant_sku_code_sequence",
        "products",
        ["tenant_id", "sku_code_date", "sku_code_sequence"],
        unique=True,
    )
    op.create_index(
        "uq_skus_tenant_source_code",
        "skus",
        ["tenant_id", "source_sku_code"],
        unique=True,
    )
    op.create_index(
        "uq_skus_tenant_product_sequence",
        "skus",
        ["tenant_id", "product_id", "sku_sequence"],
        unique=True,
    )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        _restore_source_codes_postgresql()
        op.drop_index("uq_skus_tenant_product_sequence", table_name="skus")
        op.drop_index("uq_skus_tenant_source_code", table_name="skus")
        op.drop_index("uq_products_tenant_sku_code_sequence", table_name="products")
        op.drop_column("skus", "sku_sequence")
        op.drop_column("skus", "source_sku_code")
        op.drop_column("products", "sku_code_sequence")
        op.drop_column("products", "sku_code_date")
        op.drop_column("tenants", "sku_prefix")
        return
    bind = op.get_bind()
    skus = sa.table(
        "skus",
        sa.column("id", sa.Uuid()),
        sa.column("sku_code", sa.String()),
        sa.column("source_sku_code", sa.String()),
    )
    rows = list(
        bind.execute(
            sa.select(skus.c.id, skus.c.sku_code, skus.c.source_sku_code)
        ).mappings()
    )
    for row in rows:
        bind.execute(
            skus.update()
            .where(skus.c.id == row.id)
            .values(sku_code=f"DOWN-{str(row.id).replace('-', '').upper()}")
        )
    for row in rows:
        bind.execute(
            skus.update()
            .where(skus.c.id == row.id)
            .values(sku_code=row.source_sku_code or row.sku_code)
        )
    op.drop_index("uq_skus_tenant_product_sequence", table_name="skus")
    op.drop_index("uq_skus_tenant_source_code", table_name="skus")
    op.drop_index("uq_products_tenant_sku_code_sequence", table_name="products")
    op.drop_column("skus", "sku_sequence")
    op.drop_column("skus", "source_sku_code")
    op.drop_column("products", "sku_code_sequence")
    op.drop_column("products", "sku_code_date")
    op.drop_column("tenants", "sku_prefix")
