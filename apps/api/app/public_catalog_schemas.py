from __future__ import annotations

from datetime import date, datetime
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
    prices_visible: bool = True
    category_layout_mode: Literal["AUTO", "HORIZONTAL", "VERTICAL", "VISITOR"] = "AUTO"
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
    packing_quantity: Decimal | None = None
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
    customer_note: str | None = Field(default=None, max_length=1000)

    @field_validator("customer_note", mode="before")
    @classmethod
    def normalize_customer_note(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


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
    packing_quantity: Decimal | None = None
    carton_count: Decimal | None = None
    id: UUID
    sku_id: UUID
    product_id: UUID | None = None
    position: int
    quantity: Decimal
    customer_note: str | None = None
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


class PublicQuoteCustomField(BaseModel):
    """One merchant-defined line-item column stored only on this document."""

    id: UUID
    label: str = Field(min_length=1, max_length=80)
    values: dict[UUID, str] = Field(default_factory=dict, max_length=200)

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[object, str] = {}
        for item_id, content in value.items():
            text = str(content).strip() if content is not None else ""
            if len(text) > 2_000:
                raise ValueError("custom field value is too long")
            normalized[item_id] = text
        return normalized


class PublicProformaInvoiceSettings(BaseModel):
    """Merchant-authored fields that turn a quotation into a usable PI."""

    invoice_number: str = Field(min_length=1, max_length=80)
    issue_date: date
    seller_name: str | None = Field(default=None, max_length=200)
    seller_contact: str = Field(default="", max_length=200)
    seller_website: str = Field(default="", max_length=500)
    seller_tax_number: str = Field(default="", max_length=100)
    seller_address: str = Field(default="", max_length=2_000)
    seller_email: str = Field(default="", max_length=320)
    seller_phone: str = Field(default="", max_length=80)
    buyer_name: str | None = Field(default=None, max_length=200)
    buyer_contact: str | None = Field(default=None, max_length=200)
    buyer_email: str | None = Field(default=None, max_length=320)
    buyer_phone: str | None = Field(default=None, max_length=80)
    buyer_address: str = Field(default="", max_length=2_000)
    incoterm: str = Field(default="", max_length=120)
    payment_terms: str = Field(default="", max_length=2_000)
    delivery_terms: str = Field(default="", max_length=2_000)
    shipment_method: str = Field(default="", max_length=200)
    port_of_loading: str = Field(default="", max_length=200)
    port_of_destination: str = Field(default="", max_length=200)
    beneficiary_name: str = Field(default="", max_length=300)
    bank_name: str = Field(default="", max_length=300)
    bank_address: str = Field(default="", max_length=2_000)
    bank_account_number: str = Field(default="", max_length=200)
    swift_code: str = Field(default="", max_length=80)
    freight: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=2)
    remarks: str = Field(default="", max_length=5_000)

    @field_validator(
        "invoice_number",
        "seller_name", "seller_contact", "seller_website", "seller_tax_number",
        "buyer_name", "buyer_contact", "buyer_email", "buyer_phone",
        "seller_address",
        "seller_email",
        "seller_phone",
        "buyer_address",
        "incoterm",
        "payment_terms",
        "delivery_terms",
        "shipment_method",
        "port_of_loading",
        "port_of_destination",
        "beneficiary_name",
        "bank_name",
        "bank_address",
        "bank_account_number",
        "swift_code",
        "remarks",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("invoice_number")
    @classmethod
    def validate_invoice_number(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("invoice number cannot contain control characters")
        return value


class PublicPackingListItem(BaseModel):
    """Document-only overrides; never change SKU master data or order quantity."""

    item_id: UUID
    name: str | None = Field(default=None, min_length=1, max_length=1000)
    article_number: str | None = Field(default=None, max_length=200)
    barcode: str | None = Field(default=None, pattern=r"^(?:[0-9]{13})?$")
    packing_quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=4)
    carton_length: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    carton_width: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    carton_height: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    carton_volume: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=8)
    gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)
    carton_count: int | None = Field(default=None, gt=0, le=100_000_000)
    last_carton_gross_weight: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=4)

    @field_validator("name", "article_number", "barcode", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PublicPackingListSettings(BaseModel):
    packing_list_number: str = Field(min_length=1, max_length=80)
    issue_date: date
    seller_name: str | None = Field(default=None, max_length=200)
    seller_contact: str = Field(default="", max_length=200)
    seller_phone: str = Field(default="", max_length=100)
    seller_email: str = Field(default="", max_length=320)
    seller_address: str = Field(default="", max_length=2000)
    buyer_name: str | None = Field(default=None, max_length=200)
    buyer_contact: str | None = Field(default=None, max_length=200)
    buyer_phone: str | None = Field(default=None, max_length=100)
    buyer_email: str | None = Field(default=None, max_length=320)
    buyer_address: str = Field(default="", max_length=2000)
    remarks: str = Field(default="", max_length=5000)
    items: list[PublicPackingListItem] = Field(default_factory=list, max_length=200)

    @field_validator("packing_list_number", "seller_name", "seller_contact", "seller_phone", "seller_email", "seller_address", "buyer_name", "buyer_contact", "buyer_phone", "buyer_email", "buyer_address", "remarks", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_items(self):
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate packing list item")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.packing_list_number):
            raise ValueError("packing list number cannot contain control characters")
        return self


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
    custom_fields: list[PublicQuoteCustomField] = Field(default_factory=list)
    proforma_invoice: PublicProformaInvoiceSettings | None = None
    packing_list: PublicPackingListSettings | None = None
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
    custom_fields: list[PublicQuoteCustomField] | None = Field(
        default=None,
        max_length=12,
    )
    proforma_invoice: PublicProformaInvoiceSettings | None = None
    packing_list: PublicPackingListSettings | None = None

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

    @field_validator("custom_fields")
    @classmethod
    def unique_custom_fields(
        cls,
        value: list[PublicQuoteCustomField] | None,
    ) -> list[PublicQuoteCustomField] | None:
        if value is None:
            return None
        ids = [field.id for field in value]
        labels = [field.label.casefold() for field in value]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate custom field id")
        if len(labels) != len(set(labels)):
            raise ValueError("duplicate custom field label")
        return value


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
    image_url: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "name",
        "description",
        "specification",
        "category",
        "unit_code",
        "image_url",
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


class PurchaseOrderSupplierOption(BaseModel):
    """Internal supplier choice for one quoted SKU.

    These records are available only from the authenticated merchant purchase
    order endpoint.  They must never be attached to a public storefront quote
    response or a customer-subaccount response.
    """

    supplier_id: str
    supplier_name: str
    supplier_code: str
    supplier_sku: str | None = None
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=20)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    moq: Decimal | None = Field(default=None, ge=0, max_digits=20)
    moq_unit: str | None = Field(default=None, max_length=32)
    lead_time_days: int | None = Field(default=None, ge=0)
    contact_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=2_000)


class PurchaseOrderItem(BaseModel):
    item_id: UUID
    position: int = Field(ge=1)
    supplier_id: str | None = Field(default=None, max_length=40)
    supplier_name: str = Field(default="未指定供应商", min_length=1, max_length=300)
    sku_code: str = Field(min_length=1, max_length=200)
    supplier_sku: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=1_000)
    specification: str = Field(default="", max_length=10_000)
    image_url: str | None = Field(default=None, max_length=2_000)
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_code: str = Field(min_length=1, max_length=32)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    notes: str = Field(default="", max_length=2_000)
    supplier_options: list[PurchaseOrderSupplierOption] = Field(default_factory=list)

    @field_validator(
        "supplier_id",
        "supplier_name",
        "sku_code",
        "supplier_sku",
        "name",
        "specification",
        "unit_code",
        "currency",
        "notes",
        mode="before",
    )
    @classmethod
    def normalize_purchase_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("currency")
    @classmethod
    def normalize_purchase_currency(cls, value: str) -> str:
        return value.upper()


class PurchaseOrderSettings(BaseModel):
    purchase_order_number: str = Field(min_length=1, max_length=80)
    issue_date: date
    items: list[PurchaseOrderItem] = Field(default_factory=list, max_length=200)
    custom_fields: list[PublicQuoteCustomField] = Field(
        default_factory=list,
        max_length=12,
    )

    @field_validator("purchase_order_number", mode="before")
    @classmethod
    def normalize_purchase_order_number(cls, value: object) -> object:
        normalized = value.strip() if isinstance(value, str) else value
        if isinstance(normalized, str) and any(
            ord(character) < 32 or ord(character) == 127 for character in normalized
        ):
            raise ValueError("purchase order number cannot contain control characters")
        return normalized

    @model_validator(mode="after")
    def unique_purchase_items(self) -> "PurchaseOrderSettings":
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate purchase order item")
        field_ids = [field.id for field in self.custom_fields]
        field_labels = [field.label.casefold() for field in self.custom_fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("duplicate purchase order custom field id")
        if len(field_labels) != len(set(field_labels)):
            raise ValueError("duplicate purchase order custom field label")
        valid_item_ids = set(item_ids)
        if any(
            item_id not in valid_item_ids
            for field in self.custom_fields
            for item_id in field.values
        ):
            raise ValueError("purchase order custom field item was not found")
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
