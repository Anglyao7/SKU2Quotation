from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .constants import DEFAULT_MEMBERSHIP_ID, DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID
from .product_center_models import AttributeDefinitionRow, SkuRow, SupplierPriceRow
from .product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
    SupplierProductRow,
)
from .public_catalog_models import PublicCatalogOfferRow, TenantPublicProfileRow


DEMO_ROWS = (
    (
        UUID("71000000-0000-0000-0000-000000000001"),
        "SKU-24018",
        "宠物无线饮水机（不锈钢款）",
        "AQ-320S",
        "WATER-FEED",
        "饮水与喂食",
        "SUP-001",
        Decimal("72"),
        Decimal("100"),
        "SOURCE",
        "不锈钢",
    ),
    (
        UUID("71000000-0000-0000-0000-000000000002"),
        "SKU-18211",
        "八片带门宠物围栏",
        "PF-8G01",
        "FENCE-TOY",
        "围栏与玩具",
        "SUP-002",
        Decimal("148"),
        Decimal("1"),
        "APPROVED",
        "钢材",
    ),
    (
        UUID("71000000-0000-0000-0000-000000000003"),
        "SKU-31008",
        "智能宠物喂食器 6L",
        "SF-6L20",
        "SMART-PET",
        "智能硬件",
        "SUP-003",
        Decimal("196"),
        Decimal("200"),
        "SOURCE",
        "ABS",
    ),
)

PUBLIC_DEMO_OFFERS = {
    "AQ-320S": (Decimal("99.00"), ["宠物饮水", "不锈钢"]),
    "PF-8G01": (Decimal("229.00"), ["宠物围栏", "钢材"]),
    "SF-6L20": (Decimal("299.00"), ["智能喂食", "ABS"]),
}


def seed_product_center_demo(session: Session) -> None:
    """Explicit local/test fixtures stored in the authoritative tables, never production data."""

    public_profile = session.get(TenantPublicProfileRow, DEFAULT_TENANT_ID)
    if public_profile is None:
        session.add(
            TenantPublicProfileRow(
                tenant_id=DEFAULT_TENANT_ID,
                slug="demo",
                description="智贸云本地演示产品目录",
                contact_email="owner@local.aitradecloud.invalid",
                publication_status="PUBLISHED",
            )
        )
    else:
        # Keep the public projection aligned with the canonical demo tenant URL.
        public_profile.slug = "demo"
        public_profile.publication_status = "PUBLISHED"

    category_by_code: dict[str, ProductCategoryRow] = {}
    for _id, _code, _name, _sku, category_code, category_name, *_rest in DEMO_ROWS:
        category = session.scalar(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == DEFAULT_TENANT_ID,
                ProductCategoryRow.code == category_code,
            )
        )
        if category is None:
            category = ProductCategoryRow(
                tenant_id=DEFAULT_TENANT_ID,
                code=category_code,
                name=category_name,
                path=category_name,
                status="ACTIVE",
            )
            session.add(category)
            session.flush()
        elif category.path == category.code:
            category.path = category.name
        category_by_code[category_code] = category
        for key, label, variant in (
            ("color", "颜色", True),
            ("size", "尺寸", True),
            ("material", "材质", False),
        ):
            definition = session.scalar(
                select(AttributeDefinitionRow).where(
                    AttributeDefinitionRow.tenant_id == DEFAULT_TENANT_ID,
                    AttributeDefinitionRow.category_id == category.id,
                    AttributeDefinitionRow.attribute_key == key,
                )
            )
            if definition is None:
                session.add(
                    AttributeDefinitionRow(
                        tenant_id=DEFAULT_TENANT_ID,
                        category_id=category.id,
                        attribute_key=key,
                        display_name=label,
                        data_type="TEXT",
                        is_variant=variant,
                    )
                )
    session.flush()

    now = datetime.now(UTC)
    for (
        product_id,
        product_code,
        name,
        sku_code,
        category_code,
        _category_name,
        supplier_id,
        price,
        moq,
        image_status,
        material,
    ) in DEMO_ROWS:
        product = session.scalar(
            select(ProductRow).where(
                ProductRow.tenant_id == DEFAULT_TENANT_ID,
                ProductRow.id == product_id,
            )
        )
        if product is None:
            product = ProductRow(
                id=product_id,
                tenant_id=DEFAULT_TENANT_ID,
                product_code=product_code,
                name=name,
                category_id=category_by_code[category_code].id,
                status="ACTIVE",
                default_unit="piece",
                created_by=DEFAULT_OWNER_USER_ID,
                updated_by=DEFAULT_OWNER_USER_ID,
            )
            session.add(product)
            session.flush()
            session.add(
                ProductAttributeRow(
                    tenant_id=DEFAULT_TENANT_ID,
                    product_id=product.id,
                    attribute_key="material",
                    value_text=material,
                    review_status="CONFIRMED",
                )
            )
            session.add(
                ProductImageRow(
                    tenant_id=DEFAULT_TENANT_ID,
                    product_id=product.id,
                    storage_provider="LOCAL_DEMO",
                    bucket="local-demo",
                    object_key=f"tenants/{DEFAULT_TENANT_ID}/demo/products/{product.id}/main.svg",
                    original_filename="placeholder.svg",
                    content_type="image/svg+xml",
                    byte_size=0,
                    sha256=("a" if image_status == "APPROVED" else "b") * 64,
                    image_role="MAIN",
                    approval_status=image_status,
                )
            )
        sku = session.scalar(
            select(SkuRow).where(
                SkuRow.tenant_id == DEFAULT_TENANT_ID,
                SkuRow.sku_code == sku_code,
            )
        )
        if sku is None:
            sku = SkuRow(
                tenant_id=DEFAULT_TENANT_ID,
                product_id=product.id,
                sku_code=sku_code,
                name=name,
                option_values={},
                default_moq=moq,
                moq_unit="piece",
                status="ACTIVE",
                created_by_user_id=DEFAULT_OWNER_USER_ID,
                updated_by_user_id=DEFAULT_OWNER_USER_ID,
            )
            session.add(sku)
            session.flush()
        source = session.scalar(
            select(SupplierProductRow).where(
                SupplierProductRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierProductRow.supplier_id == supplier_id,
                SupplierProductRow.product_id == product.id,
                SupplierProductRow.supplier_sku == sku_code,
            )
        )
        if source is None:
            source = SupplierProductRow(
                tenant_id=DEFAULT_TENANT_ID,
                supplier_id=supplier_id,
                product_id=product.id,
                sku_id=sku.id,
                supplier_sku=sku_code,
                supplier_product_name=name,
                moq=moq,
                moq_unit="piece",
                lead_time_days=15,
                status="ACTIVE",
            )
            session.add(source)
            session.flush()
        existing_price = session.scalar(
            select(SupplierPriceRow.id).where(
                SupplierPriceRow.tenant_id == DEFAULT_TENANT_ID,
                SupplierPriceRow.supplier_product_id == source.id,
            )
        )
        if existing_price is None:
            session.add(
                SupplierPriceRow(
                    tenant_id=DEFAULT_TENANT_ID,
                    supplier_product_id=source.id,
                    sku_id=sku.id,
                    min_quantity=moq,
                    unit_price=price,
                    currency="CNY",
                    unit_code="piece",
                    valid_from=now,
                    valid_to=now + timedelta(days=180),
                    status="CONFIRMED",
                    confirmed_by_membership_id=DEFAULT_MEMBERSHIP_ID,
                    confirmed_at=now,
                )
            )
        public_offer = session.scalar(
            select(PublicCatalogOfferRow).where(
                PublicCatalogOfferRow.tenant_id == DEFAULT_TENANT_ID,
                PublicCatalogOfferRow.sku_id == sku.id,
            )
        )
        if public_offer is None:
            public_price, public_tags = PUBLIC_DEMO_OFFERS[sku_code]
            session.add(
                PublicCatalogOfferRow(
                    tenant_id=DEFAULT_TENANT_ID,
                    sku_id=sku.id,
                    unit_price=public_price,
                    currency="CNY",
                    tags=public_tags,
                    publication_status="PUBLISHED",
                    published_at=now,
                )
            )
    session.commit()
