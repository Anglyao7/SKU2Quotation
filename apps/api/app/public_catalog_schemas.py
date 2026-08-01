from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .announcement_schemas import PublicAnnouncementResponse
from .quote_template_schemas import QuoteExcelTemplateRenderSpec

PUBLIC_DRAFT_DISCLAIMER = (
    "此文件仅为报价申请草稿和价格预估，当前状态为待人工确认；"
    "在商家完成审核并签发正式报价前，不构成要约、承诺或正式报价。"
)
PUBLIC_DRAFT_DISCLAIMER_VERSION = "public-draft-v1"
PUBLIC_PRIVACY_NOTICE_VERSION = "privacy-v1"


class PublicStoreResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    description: str | None
    logo_url: str | None
    contact_email: str | None
    contact_phone: str | None
    default_currency: str
    locale: str
    source_locale: str = "zh-CN"
    available_locales: list[str] = Field(default_factory=lambda: ["zh-CN"])
    all_products_position: int = Field(default=0, ge=0)
    announcements: list[PublicAnnouncementResponse] = Field(default_factory=list)
    quote_notice: str = PUBLIC_DRAFT_DISCLAIMER


class PublicCategoryOption(BaseModel):
    value: str
    label: str


class PublicSkuResponse(BaseModel):
    id: UUID
    product_id: UUID
    sku_code: str
    name: str
    description: str | None
    category: str | None
    category_label: str | None = None
    category_color: str | None = None
    tags: list[str]
    display_tag: str | None = None
    tag_color: str | None = None
    price: Decimal
    currency: str
    unit_code: str
    image_url: str | None
    product_version: int
    sku_version: int
    specification: str | None = None
    option_values: dict[str, Any] = Field(default_factory=dict)
    source_locale: str = "zh-CN"
    locale: str = "zh-CN"
    translation_status: Literal["SOURCE", "TRANSLATED", "FALLBACK"] = "SOURCE"


class PublicSkuPage(BaseModel):
    items: list[PublicSkuResponse]
    total: int
    page: int
    page_size: int
    pages: int
    categories: list[str]
    category_options: list[PublicCategoryOption] = Field(default_factory=list)
    tags: list[str]
    source_locale: str = "zh-CN"
    locale: str = "zh-CN"
    all_products_position: int = Field(default=0, ge=0)


class PublicProductSummary(BaseModel):
    id: UUID
    product_code: str | None
    name: str
    description: str | None
    category: str | None
    category_label: str | None = None
    category_color: str | None = None
    tags: list[str] = Field(default_factory=list)
    display_tag: str | None = None
    tag_color: str | None = None
    price_from: Decimal
    price_to: Decimal
    currency: str
    unit_code: str
    image_url: str | None
    sku_count: int = Field(ge=1)
    product_version: int
    source_locale: str = "zh-CN"
    locale: str = "zh-CN"
    translation_status: Literal["SOURCE", "TRANSLATED", "FALLBACK"] = "SOURCE"


class PublicProductDetail(PublicProductSummary):
    skus: list[PublicSkuResponse]


class PublicProductPage(BaseModel):
    items: list[PublicProductSummary]
    total: int
    page: int
    page_size: int
    pages: int
    categories: list[str]
    category_options: list[PublicCategoryOption] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_locale: str = "zh-CN"
    locale: str = "zh-CN"
    all_products_position: int = Field(default=0, ge=0)


class PublicCartItem(BaseModel):
    sku_id: UUID
    quantity: Decimal = Field(gt=0, le=1_000_000, decimal_places=6)


class PublicQuoteDraftCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=160)
    customer_company: str | None = Field(default=None, max_length=200)
    customer_email: str | None = Field(default=None, max_length=320)
    customer_phone: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=5000)
    privacy_acknowledged: Literal[True]
    items: list[PublicCartItem] = Field(min_length=1, max_length=200)

    @field_validator(
        "customer_name",
        "customer_company",
        "customer_email",
        "customer_phone",
        mode="before",
    )
    @classmethod
    def strip_customer_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_skus(self):
        sku_ids = [item.sku_id for item in self.items]
        if len(sku_ids) != len(set(sku_ids)):
            raise ValueError("duplicate sku_id in cart")
        return self


class PublicQuoteDraftItemResponse(BaseModel):
    id: UUID
    sku_id: UUID
    position: int
    quantity: Decimal
    sku_code_snapshot: str
    name_snapshot: str
    description_snapshot: str | None
    specification_snapshot: str | None
    option_values_snapshot: dict[str, Any]
    category_snapshot: str | None
    tags_snapshot: list[str]
    image_url_snapshot: str | None
    unit_code_snapshot: str
    currency_snapshot: str
    unit_price_snapshot: Decimal
    line_total: Decimal
    product_version: int
    sku_version: int


class PublicQuoteDraftResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    quote_number: str
    status: str
    customer_name: str
    customer_company: str | None
    customer_email: str | None
    customer_phone: str | None
    notes: str | None
    currency: str
    subtotal: Decimal
    total: Decimal
    total_amount: Decimal
    valid_until: datetime
    created_at: datetime
    content_hash: str
    disclaimer: str = PUBLIC_DRAFT_DISCLAIMER
    disclaimer_version: str = PUBLIC_DRAFT_DISCLAIMER_VERSION
    items: list[PublicQuoteDraftItemResponse]
    download_token: str | None = None
    download_expires_at: datetime | None = None
    pdf_url: str | None = None
    xlsx_url: str | None = None


class PublicQuoteDraftSummary(BaseModel):
    id: UUID
    quote_number: str
    status: str
    customer_name: str
    customer_company: str | None
    currency: str
    total_amount: Decimal
    valid_until: datetime
    created_at: datetime


class PublicQuoteDocument(BaseModel):
    tenant_name: str
    contact_email: str | None
    contact_phone: str | None
    quote: PublicQuoteDraftResponse
    excel_template: QuoteExcelTemplateRenderSpec | None = None
