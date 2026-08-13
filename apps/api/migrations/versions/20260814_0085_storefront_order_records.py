"""Record immutable storefront orders when merchant quotes are confirmed.

Revision ID: 20260814_0085
Revises: 20260813_0084
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260814_0085"
down_revision = "20260813_0084"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_DOCUMENT = sa.JSON().with_variant(
    postgresql.JSONB(none_as_null=True),
    "postgresql",
)
U = lambda: sa.Uuid(as_uuid=True)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _legacy_order_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    drafts = sa.table(
        "public_quote_drafts",
        sa.column("id", U()),
        sa.column("tenant_id", U()),
        sa.column("request_number", sa.String()),
        sa.column("status", sa.String()),
        sa.column("submitted_by_membership_id", U()),
        sa.column("customer_name", sa.String()),
        sa.column("customer_company", sa.String()),
        sa.column("customer_email", sa.String()),
        sa.column("customer_phone", sa.String()),
        sa.column("document_locale", sa.String()),
        sa.column("currency", sa.String()),
        sa.column("subtotal_amount", sa.Numeric(20, 2)),
        sa.column("estimated_total", sa.Numeric(20, 2)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    items = sa.table(
        "public_quote_draft_items",
        sa.column("quote_draft_id", U()),
        sa.column("position", sa.Integer()),
        sa.column("sku_id", U()),
        sa.column("product_id_snapshot", U()),
        sa.column("product_version", sa.BigInteger()),
        sa.column("sku_version", sa.BigInteger()),
        sa.column("sku_code_snapshot", sa.String()),
        sa.column("name_snapshot", sa.String()),
        sa.column("description_snapshot", sa.Text()),
        sa.column("specification_snapshot", sa.Text()),
        sa.column("option_values_snapshot", JSON_DOCUMENT),
        sa.column("category_snapshot", sa.String()),
        sa.column("tags_snapshot", JSON_DOCUMENT),
        sa.column("image_url_snapshot", sa.String()),
        sa.column("minimum_order_quantity", sa.Numeric(20, 6)),
        sa.column("unit_code_snapshot", sa.String()),
        sa.column("currency_snapshot", sa.String()),
        sa.column("unit_price_snapshot", sa.Numeric(20, 2)),
        sa.column("quantity", sa.Numeric(20, 6)),
        sa.column("line_total", sa.Numeric(20, 2)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    records: list[dict[str, Any]] = []
    confirmed_drafts = bind.execute(
        sa.select(drafts).where(
            drafts.c.status.in_(("CONFIRMED", "COMPLETED")),
            drafts.c.deleted_at.is_(None),
        )
    ).mappings()
    for draft in confirmed_drafts:
        item_rows = list(
            bind.execute(
                sa.select(items)
                .where(
                    items.c.quote_draft_id == draft["id"],
                    items.c.deleted_at.is_(None),
                )
                .order_by(items.c.position)
            ).mappings()
        )
        if not item_rows:
            # A malformed legacy draft cannot become a reliable order fact.
            continue
        snapshot_items = [
            {
                "position": item["position"],
                "sku_id": str(item["sku_id"]),
                "product_id": str(item["product_id_snapshot"]),
                "product_version": item["product_version"],
                "sku_version": item["sku_version"],
                "sku_code": item["sku_code_snapshot"],
                "name": item["name_snapshot"],
                "description": item["description_snapshot"],
                "specification": item["specification_snapshot"],
                "option_values": _json_value(item["option_values_snapshot"] or {}),
                "category": item["category_snapshot"],
                "tags": _json_value(item["tags_snapshot"] or []),
                "image_url": item["image_url_snapshot"],
                "minimum_order_quantity": str(item["minimum_order_quantity"]),
                "quantity": str(item["quantity"]),
                "unit_code": item["unit_code_snapshot"],
                "currency": item["currency_snapshot"],
                "unit_price": str(item["unit_price_snapshot"]),
                "line_total": str(item["line_total"]),
            }
            for item in item_rows
        ]
        confirmed_at = draft["updated_at"] or draft["created_at"]
        snapshot = {
            "schema_version": "storefront-order-v1",
            "source_quote": {
                "id": str(draft["id"]),
                "number": draft["request_number"],
            },
            "customer": {
                "name": draft["customer_name"],
                "company": draft["customer_company"],
                "email": draft["customer_email"],
                "phone": draft["customer_phone"],
            },
            "document_locale": draft["document_locale"] or "zh-CN",
            "currency": draft["currency"],
            "subtotal_amount": str(draft["subtotal_amount"]),
            "total_amount": str(draft["estimated_total"]),
            "items": snapshot_items,
            "confirmation": {
                "confirmed_at": confirmed_at.isoformat(),
                "time_source": "legacy_quote_updated_at",
            },
        }
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        records.append(
            {
                "id": uuid4(),
                "tenant_id": draft["tenant_id"],
                "source_quote_draft_id": draft["id"],
                "order_number": draft["request_number"],
                "status": draft["status"],
                "submitted_by_membership_id": draft["submitted_by_membership_id"],
                "customer_name": draft["customer_name"],
                "customer_company": draft["customer_company"],
                "customer_email": draft["customer_email"],
                "customer_phone": draft["customer_phone"],
                "document_locale": draft["document_locale"] or "zh-CN",
                "currency": draft["currency"],
                "subtotal_amount": draft["subtotal_amount"],
                "total_amount": draft["estimated_total"],
                "item_count": len(item_rows),
                "total_quantity": sum(
                    (Decimal(item["quantity"]) for item in item_rows),
                    Decimal("0"),
                ),
                "confirmed_by_membership_id": None,
                "confirmed_at": confirmed_at,
                "completed_at": confirmed_at if draft["status"] == "COMPLETED" else None,
                "cancelled_at": None,
                "snapshot": snapshot,
                "content_hash": hashlib.sha256(encoded).hexdigest(),
                "created_at": confirmed_at,
                "updated_at": draft["updated_at"] or confirmed_at,
                "deleted_at": None,
            }
        )
    return records


def upgrade() -> None:
    op.create_table(
        "storefront_order_records",
        sa.Column("id", U(), nullable=False),
        sa.Column("tenant_id", U(), nullable=False),
        sa.Column("source_quote_draft_id", U(), nullable=False),
        sa.Column("order_number", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("submitted_by_membership_id", U(), nullable=True),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_company", sa.String(200), nullable=True),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_phone", sa.String(80), nullable=True),
        sa.Column("document_locale", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("total_quantity", sa.Numeric(20, 6), nullable=False),
        sa.Column("confirmed_by_membership_id", U(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('CONFIRMED', 'COMPLETED', 'CANCELLED')",
            name="ck_storefront_order_records_status_allowed",
        ),
        sa.CheckConstraint(
            "subtotal_amount >= 0",
            name="ck_storefront_order_records_subtotal_nonnegative",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_storefront_order_records_total_nonnegative",
        ),
        sa.CheckConstraint(
            "item_count > 0",
            name="ck_storefront_order_records_item_count_positive",
        ),
        sa.CheckConstraint(
            "total_quantity > 0",
            name="ck_storefront_order_records_total_quantity_positive",
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_storefront_order_records_content_hash_sha256_length",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_storefront_order_records_currency_format",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status <> 'COMPLETED')",
            name="ck_storefront_order_records_completion_time_required",
        ),
        sa.CheckConstraint(
            "(status = 'CANCELLED' AND cancelled_at IS NOT NULL) OR "
            "(status <> 'CANCELLED')",
            name="ck_storefront_order_records_cancellation_time_required",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_storefront_order_records_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_quote_draft_id"],
            ["public_quote_drafts.tenant_id", "public_quote_drafts.id"],
            name="fk_storefront_order_records_tenant_quote",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submitted_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_storefront_order_records_tenant_submitter",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "confirmed_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_storefront_order_records_tenant_confirmer",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_order_records"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_storefront_order_records_tenant_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_quote_draft_id",
            name="uq_storefront_order_records_tenant_quote",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "order_number",
            name="uq_storefront_order_records_tenant_number",
        ),
    )
    op.create_index(
        "ix_storefront_order_records_tenant_confirmed",
        "storefront_order_records",
        ["tenant_id", "confirmed_at"],
    )
    op.create_index(
        "ix_storefront_order_records_tenant_status_confirmed",
        "storefront_order_records",
        ["tenant_id", "status", "confirmed_at"],
    )
    op.create_index(
        "ix_storefront_order_records_tenant_customer_confirmed",
        "storefront_order_records",
        ["tenant_id", "submitted_by_membership_id", "confirmed_at"],
    )

    # Offline SQL generation has no result-producing database connection.
    # Existing-order backfill therefore runs only during a real migration;
    # all schema and RLS statements remain present in the offline artifact.
    records = [] if op.get_context().as_sql else _legacy_order_rows(op.get_bind())
    if records:
        order_records = sa.table(
            "storefront_order_records",
            sa.column("id", U()),
            sa.column("tenant_id", U()),
            sa.column("source_quote_draft_id", U()),
            sa.column("order_number", sa.String()),
            sa.column("status", sa.String()),
            sa.column("submitted_by_membership_id", U()),
            sa.column("customer_name", sa.String()),
            sa.column("customer_company", sa.String()),
            sa.column("customer_email", sa.String()),
            sa.column("customer_phone", sa.String()),
            sa.column("document_locale", sa.String()),
            sa.column("currency", sa.String()),
            sa.column("subtotal_amount", sa.Numeric(20, 2)),
            sa.column("total_amount", sa.Numeric(20, 2)),
            sa.column("item_count", sa.Integer()),
            sa.column("total_quantity", sa.Numeric(20, 6)),
            sa.column("confirmed_by_membership_id", U()),
            sa.column("confirmed_at", sa.DateTime(timezone=True)),
            sa.column("completed_at", sa.DateTime(timezone=True)),
            sa.column("cancelled_at", sa.DateTime(timezone=True)),
            sa.column("snapshot", JSON_DOCUMENT),
            sa.column("content_hash", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
            sa.column("deleted_at", sa.DateTime(timezone=True)),
        )
        op.bulk_insert(order_records, records)

    if op.get_bind().dialect.name == "postgresql":
        tenant = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
        op.execute('ALTER TABLE "storefront_order_records" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE "storefront_order_records" FORCE ROW LEVEL SECURITY')
        op.execute(
            'CREATE POLICY "storefront_order_records_tenant_isolation" '
            'ON "storefront_order_records" FOR ALL '
            f"USING (tenant_id = {tenant}) WITH CHECK (tenant_id = {tenant})"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_storefront_order_records_tenant_customer_confirmed",
        table_name="storefront_order_records",
    )
    op.drop_index(
        "ix_storefront_order_records_tenant_status_confirmed",
        table_name="storefront_order_records",
    )
    op.drop_index(
        "ix_storefront_order_records_tenant_confirmed",
        table_name="storefront_order_records",
    )
    op.drop_table("storefront_order_records")
