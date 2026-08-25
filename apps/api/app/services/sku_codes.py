from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductRow


SKU_PREFIX_LENGTH = 4
SKU_VARIANT_LIMIT = 999


def derive_merchant_sku_prefix(name: str, *, slug: str = "") -> str:
    """Return a stable four-character ASCII prefix for a merchant."""

    normalized_name = unicodedata.normalize("NFKC", name)
    english = "".join(re.findall(r"[A-Za-z0-9]", normalized_name)).upper()
    if english:
        return english[:SKU_PREFIX_LENGTH].ljust(SKU_PREFIX_LENGTH, "X")
    normalized_slug = unicodedata.normalize("NFKC", slug)
    slug_ascii = "".join(re.findall(r"[A-Za-z0-9]", normalized_slug)).upper()
    return (slug_ascii or "SHOP")[:SKU_PREFIX_LENGTH].ljust(
        SKU_PREFIX_LENGTH,
        "X",
    )


def normalize_merchant_sku_prefix(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", normalized):
        raise ValueError("merchant SKU prefix must contain exactly four letters or digits")
    return normalized


def merchant_business_date(
    tenant: TenantRow,
    *,
    issued_at: datetime | None = None,
) -> date:
    timestamp = issued_at or utcnow()
    try:
        timezone = ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        timezone = ZoneInfo("UTC")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ZoneInfo("UTC"))
    return timestamp.astimezone(timezone).date()


def format_sku_code(
    *,
    merchant_prefix: str,
    product_date: date,
    product_sequence: int,
    sku_sequence: int,
) -> str:
    prefix = normalize_merchant_sku_prefix(merchant_prefix)
    if product_sequence < 1:
        raise ValueError("product sequence must be positive")
    if not 1 <= sku_sequence <= SKU_VARIANT_LIMIT:
        raise ValueError("SKU sequence must be between 1 and 999")
    product_segment = f"{product_date:%y%m%d}{product_sequence:03d}"
    return f"{prefix}-{product_segment}-{sku_sequence:03d}"


def ensure_product_code_identity(
    session: Session,
    *,
    tenant: TenantRow,
    product: ProductRow,
    issued_at: datetime | None = None,
) -> None:
    if product.sku_code_date is not None and product.sku_code_sequence is not None:
        return
    business_date = merchant_business_date(tenant, issued_at=issued_at)
    last_sequence = session.scalar(
        select(func.max(ProductRow.sku_code_sequence))
        .where(
            ProductRow.tenant_id == tenant.id,
            ProductRow.sku_code_date == business_date,
        )
        .execution_options(include_deleted=True)
    )
    product.sku_code_date = business_date
    product.sku_code_sequence = int(last_sequence or 0) + 1


def issue_sku_codes(
    session: Session,
    *,
    tenant: TenantRow,
    product: ProductRow,
    count: int,
    issued_at: datetime | None = None,
) -> list[tuple[str, int]]:
    if count < 1:
        return []
    ensure_product_code_identity(
        session,
        tenant=tenant,
        product=product,
        issued_at=issued_at,
    )
    session.flush()
    last_sequence = int(
        session.scalar(
            select(func.max(SkuRow.sku_sequence))
            .where(
                SkuRow.tenant_id == tenant.id,
                SkuRow.product_id == product.id,
            )
            .execution_options(include_deleted=True)
        )
        or 0
    )
    legacy_count = int(
        session.scalar(
            select(func.count(SkuRow.id))
            .where(
                SkuRow.tenant_id == tenant.id,
                SkuRow.product_id == product.id,
                SkuRow.sku_sequence.is_(None),
            )
            .execution_options(include_deleted=True)
        )
        or 0
    )
    first_sequence = max(last_sequence, legacy_count) + 1
    final_sequence = first_sequence + count - 1
    if final_sequence > SKU_VARIANT_LIMIT:
        raise ApplicationError(
            "SKU_SEQUENCE_LIMIT_EXCEEDED",
            "一个商品最多支持 999 个 SKU 规格。",
            kind="conflict",
        )
    assert product.sku_code_date is not None
    assert product.sku_code_sequence is not None
    return [
        (
            format_sku_code(
                merchant_prefix=tenant.sku_prefix,
                product_date=product.sku_code_date,
                product_sequence=product.sku_code_sequence,
                sku_sequence=sequence,
            ),
            sequence,
        )
        for sequence in range(first_sequence, final_sequence + 1)
    ]


class CatalogSkuCodeAllocator:
    """Allocate many catalog codes in memory while a tenant write lock is held."""

    def __init__(
        self,
        *,
        tenant: TenantRow,
        products: list[ProductRow],
        skus: list[SkuRow],
        issued_at: datetime | None = None,
    ) -> None:
        self.tenant = tenant
        self.business_date = merchant_business_date(tenant, issued_at=issued_at)
        self.next_product_sequence = max(
            (
                int(product.sku_code_sequence)
                for product in products
                if product.sku_code_date == self.business_date
                and product.sku_code_sequence is not None
            ),
            default=0,
        )
        self.next_sku_sequence_by_product: dict[object, int] = {}
        skus_by_product: dict[object, list[SkuRow]] = {}
        for sku in skus:
            skus_by_product.setdefault(sku.product_id, []).append(sku)
        for product_id, product_skus in skus_by_product.items():
            self.next_sku_sequence_by_product[product_id] = max(
                max(
                    (
                        int(sku.sku_sequence)
                        for sku in product_skus
                        if sku.sku_sequence is not None
                    ),
                    default=0,
                ),
                len(product_skus),
            )

    def ensure_product(self, product: ProductRow) -> None:
        if product.sku_code_date is None or product.sku_code_sequence is None:
            self.next_product_sequence += 1
            product.sku_code_date = self.business_date
            product.sku_code_sequence = self.next_product_sequence

    def reserve(self, product: ProductRow, sku_sequence: int | None) -> None:
        """Record a sequence already attached to a product during a merge.

        Imports can move an archived SKU onto a newly selected product before
        creating the next SKU in the same transaction.  Such a moved row is
        not part of the allocator's initial snapshot, so make it visible to
        subsequent allocations and avoid reusing its sequence.
        """

        if sku_sequence is None:
            return
        product_id = product.id
        current = self.next_sku_sequence_by_product.get(product_id, 0)
        self.next_sku_sequence_by_product[product_id] = max(
            current,
            int(sku_sequence),
        )

    def issue(self, product: ProductRow) -> tuple[str, int]:
        self.ensure_product(product)
        sku_sequence = self.next_sku_sequence_by_product.get(product.id, 0) + 1
        if sku_sequence > SKU_VARIANT_LIMIT:
            raise ApplicationError(
                "SKU_SEQUENCE_LIMIT_EXCEEDED",
                "一个商品最多支持 999 个 SKU 规格。",
                kind="conflict",
            )
        self.next_sku_sequence_by_product[product.id] = sku_sequence
        assert product.sku_code_date is not None
        assert product.sku_code_sequence is not None
        return (
            format_sku_code(
                merchant_prefix=self.tenant.sku_prefix,
                product_date=product.sku_code_date,
                product_sequence=product.sku_code_sequence,
                sku_sequence=sku_sequence,
            ),
            sku_sequence,
        )
