from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .announcement_schemas import PublicAnnouncementResponse
from .quote_template_schemas import QuoteExcelTemplateRenderSpec, QuoteTemplateField
from .storefront_locales import StorefrontLocale
from .storefront_footer import StorefrontFooterSection
from .storefront_page_schemas import PublicStorefrontPageLink
from .support_schemas import PublicSupportWidgetResponse

PUBLIC_DRAFT_DISCLAIMER = (
    "此文件仅为报价申请草稿和价格预估，当前状态为待人工确认；"
    "在商家完成审核并签发正式报价前，不构成要约、承诺或正式报价。"
)
PUBLIC_DRAFT_DISCLAIMER_VERSION = "public-draft-v1"
PUBLIC_PRIVACY_NOTICE_VERSION = "privacy-v1"

QuoteDocumentStyle = Literal["indigo", "emerald", "gold", "slate", "rose"]
PUBLIC_QUOTE_PDF_MAX_COLUMNS = 5


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
    hot_products_enabled: bool = False
    category_showcase_enabled: bool = True
    exchange_rates_enabled: bool = True
    ai_search_questions: list[str] = Field(default_factory=list)
    popular_search_terms: list[str] = Field(default_factory=list)
    announcements: list[PublicAnnouncementResponse] = Field(default_factory=list)
    support_widget: PublicSupportWidgetResponse
    footer_sections: list[StorefrontFooterSection] = Field(default_factory=list)
    custom_pages: list[PublicStorefrontPageLink] = Field(default_factory=list)
    storefront_scope: Literal["MERCHANT", "CUSTOMER_SUBACCOUNT"] = "MERCHANT"
    account_id: UUID | None = None
    quote_notice: str = PUBLIC_DRAFT_DISCLAIMER


class PublicExchangeRate(BaseModel):
    currency: str
    name: str
    symbol: str
    rate: Decimal | None = Field(
        default=None,
        description="CNY value of one unit of this currency.",
    )
    base_currency: str = "CNY"
    rate_date: str | None = None
    source: str = "Frankfurter"


class PublicExchangeRateResponse(BaseModel):
    observed_at: datetime
    base_currency: str = "CNY"
    exchange_rates: list[PublicExchangeRate] = Field(default_factory=list)
    rate_date: str | None = None
    rate_source: str = "Frankfurter"


class PublicCategoryOption(BaseModel):
    value: str
    label: str
    id: UUID | None = None
    parent_id: UUID | None = None
    cover_image_url: str | None = None


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
    source_updated_at: datetime
    translation_source_hash: str = Field(min_length=64, max_length=64)
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
    category_showcase_enabled: bool = True


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
    source_updated_at: datetime
    translation_source_hash: str = Field(min_length=64, max_length=64)
    source_locale: str = "zh-CN"
    locale: str = "zh-CN"
    translation_status: Literal["SOURCE", "TRANSLATED", "FALLBACK"] = "SOURCE"


class PublicProductDetail(PublicProductSummary):
    image_urls: list[str] = Field(default_factory=list)
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
    hot_products_enabled: bool = False
    category_showcase_enabled: bool = True
    hot_sort_applied: bool = False


class PublicImageSearchResult(BaseModel):
    product: PublicProductSummary
    matched_image_id: UUID
    similarity: float = Field(ge=-1, le=1)
    match_percent: float = Field(ge=0, le=100)
    confidence: Literal["HIGH", "MEDIUM", "REFERENCE"]


class PublicImageSearchResponse(BaseModel):
    id: UUID
    status: Literal["COMPLETED", "INDEX_EMPTY"]
    results: list[PublicImageSearchResult]
    warnings: list[str] = Field(default_factory=list)


class PublicCartItem(BaseModel):
    sku_id: UUID
    quantity: Decimal = Field(gt=0, le=1_000_000, decimal_places=6)


class PublicQuoteDraftCreate(BaseModel):
    locale: StorefrontLocale = "zh-CN"
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
    product_id: UUID | None = None
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


class PublicQuoteExtraInformation(BaseModel):
    """Merchant-authored key/value information shown below quote lines."""

    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=2_000)

    @field_validator("title", "content", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PublicQuoteDraftResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    quote_number: str
    request_number: str | None = None
    status: str
    customer_name: str
    customer_company: str | None
    customer_email: str | None
    customer_phone: str | None
    # A normalized two-letter country code captured at submission time.  It is
    # safe for the merchant workspace and avoids exposing or retaining the
    # visitor's raw IP address in the quote payload.
    visitor_country_code: str | None = None
    # This flag is populated for authenticated merchant workspaces.  It lets
    # an owner view a child-account inquiry without accidentally showing edit
    # controls.  Public storefront responses keep the default ``False``.
    read_only: bool = False
    notes: str | None
    locale: StorefrontLocale = "zh-CN"
    document_style: QuoteDocumentStyle = "indigo"
    quote_template_id: UUID | None = None
    visible_columns: list[QuoteTemplateField] = Field(default_factory=list)
    currency: str
    subtotal: Decimal
    total: Decimal
    total_amount: Decimal
    valid_until: datetime
    created_at: datetime
    updated_at: datetime
    content_hash: str
    disclaimer: str = PUBLIC_DRAFT_DISCLAIMER
    disclaimer_version: str = PUBLIC_DRAFT_DISCLAIMER_VERSION
    extra_information: list[PublicQuoteExtraInformation] = Field(default_factory=list)
    items: list[PublicQuoteDraftItemResponse]
    download_token: str | None = None
    download_expires_at: datetime | None = None
    pdf_url: str | None = None
    xlsx_url: str | None = None


class PublicQuoteDraftSettingsUpdate(BaseModel):
    """Presentation settings used by the merchant quote workspace."""

    locale: StorefrontLocale = "zh-CN"
    style: QuoteDocumentStyle = "indigo"
    template_id: UUID | None = None
    quote_number: str | None = Field(default=None, max_length=80)
    # PDF is rendered on portrait A4. More than five independent columns make
    # the content unreadable; Excel export keeps its complete mapped columns.
    visible_columns: list[QuoteTemplateField] | None = Field(
        default=None,
        max_length=PUBLIC_QUOTE_PDF_MAX_COLUMNS,
    )
    extra_information: list[PublicQuoteExtraInformation] | None = Field(
        default=None,
        max_length=20,
    )

    @field_validator("quote_number", mode="before")
    @classmethod
    def normalize_quote_number(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("quote number cannot be empty")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("quote number cannot contain control characters")
        return normalized

    @field_validator("visible_columns")
    @classmethod
    def unique_visible_columns(
        cls,
        value: list[QuoteTemplateField] | None,
    ) -> list[QuoteTemplateField] | None:
        return list(dict.fromkeys(value)) if value is not None else None


class PublicQuoteDraftCurrencyConversion(BaseModel):
    """Convert the current quote draft into a selected settlement currency."""

    target_currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )

    @field_validator("target_currency")
    @classmethod
    def normalize_target_currency(cls, value: str) -> str:
        return value.strip().upper()


class PublicQuoteDraftItemPriceUpdate(BaseModel):
    """A merchant's price override for one line in a pending quotation."""

    unit_price: Decimal = Field(
        ge=0,
        max_digits=20,
    )


class PublicQuoteDraftItemPatch(BaseModel):
    """Editable customer-facing fields for one quote line."""

    item_id: UUID
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=20)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=20)
    name: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    specification: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, max_length=200)
    unit_code: str | None = Field(default=None, max_length=32)

    @field_validator(
        "name",
        "description",
        "specification",
        "category",
        "unit_code",
        mode="before",
    )
    @classmethod
    def normalize_editable_text(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip()

    @model_validator(mode="after")
    def require_a_change(self) -> "PublicQuoteDraftItemPatch":
        if not self.model_fields_set - {"item_id"}:
            raise ValueError("at least one quote item field must be provided")
        for field in ("name", "unit_code"):
            if field in self.model_fields_set and not getattr(self, field):
                raise ValueError(f"{field} cannot be empty")
        return self


class PublicQuoteDraftItemsUpdate(BaseModel):
    items: list[PublicQuoteDraftItemPatch] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_item_ids(self) -> "PublicQuoteDraftItemsUpdate":
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate quote item id")
        return self


class PublicQuoteDraftPriceAdjustment(BaseModel):
    """Signed percentage applied to every current quote-line price."""

    percentage: Decimal = Field(ge=-100, le=10000, max_digits=8)


class PublicQuoteDraftSummary(BaseModel):
    id: UUID
    quote_number: str
    status: str
    customer_name: str
    customer_company: str | None
    visitor_country_code: str | None = None
    read_only: bool = False
    locale: StorefrontLocale = "zh-CN"
    currency: str
    total_amount: Decimal
    valid_until: datetime
    created_at: datetime
    updated_at: datetime


class PublicQuoteDraftStatusUpdate(BaseModel):
    status: Literal["CONFIRMED", "COMPLETED", "CANCELLED"]


class StorefrontOrderCurrencyStatistics(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    total_amount: Decimal = Field(ge=0)
    completed_amount: Decimal = Field(ge=0)
    order_count: int = Field(ge=0)


class StorefrontOrderPeriodStatistics(BaseModel):
    start_at: datetime
    end_at: datetime
    order_count: int = Field(ge=0)
    completed_order_count: int = Field(ge=0)
    cancelled_order_count: int = Field(ge=0)
    amounts: list[StorefrontOrderCurrencyStatistics] = Field(default_factory=list)


class StorefrontOrderStatistics(BaseModel):
    timezone: str
    current_month: StorefrontOrderPeriodStatistics
    current_year: StorefrontOrderPeriodStatistics


class PublicQuoteDocument(BaseModel):
    tenant_name: str
    contact_email: str | None
    contact_phone: str | None
    quote: PublicQuoteDraftResponse
    excel_template: QuoteExcelTemplateRenderSpec | None = None
    style: QuoteDocumentStyle = "indigo"
