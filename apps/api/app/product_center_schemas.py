from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class ProductCategorySummary(BaseModel):
    id: UUID
    code: str
    name: str


class ProductOfferSummary(BaseModel):
    supplier_product_id: UUID
    supplier_id: str
    supplier_name: str
    supplier_sku: str | None
    sku_id: UUID | None
    moq: Decimal | None
    moq_unit: str | None
    lead_time_days: int | None
    unit_price: Decimal | None = None
    currency: str | None = None
    price_validity: Literal["VALID", "EXPIRING", "EXPIRED", "UNKNOWN"]
    valid_to: datetime | None = None


class ProductCard(BaseModel):
    id: UUID
    product_code: str | None
    name: str
    status: str
    category: ProductCategorySummary | None
    material: str | None
    sku_count: int
    supplier_count: int
    primary_image_url: str | None
    image_status: Literal["APPROVED", "SOURCE", "NONE"]
    current_offer: ProductOfferSummary | None
    current_version: int
    updated_at: datetime
    capabilities: list[str]
    # Compatibility aliases retained while the existing Web shell migrates.
    model: str
    supplier: str
    price: Decimal | None
    currency: str | None
    moq: Decimal | None
    tags: list[str]


class SkuResponse(BaseModel):
    id: UUID
    product_id: UUID
    sku_code: str
    name: str | None
    option_values: dict[str, Any]
    barcode: str | None
    default_moq: Decimal | None
    moq_unit: str | None
    weight: Decimal | None
    weight_unit: str | None
    status: str
    version: int
    updated_at: datetime


class SkuSupplierSummary(BaseModel):
    count: int = Field(ge=0)
    primary_supplier_id: str | None = None
    primary_supplier_name: str | None = None
    names: list[str] = Field(default_factory=list)


class SkuListItem(BaseModel):
    id: UUID
    sku_code: str
    name: str
    product_id: UUID
    product_code: str | None
    product_name: str
    category: ProductCategorySummary | None
    tags: list[str]
    supplier_summary: SkuSupplierSummary
    default_moq: Decimal | None
    moq_unit: str | None
    packing_quantity: str | None = None
    public_price: Decimal | None
    public_currency: str | None
    public_offer_status: Literal["DRAFT", "PUBLISHED", "SUSPENDED"] | None
    status: str
    version: int
    updated_at: datetime
    source_type: Literal["PRODUCT_TEMPLATE", "LEGACY_IMPORT", "MANUAL"]
    source_filename: str | None
    source_imported_at: datetime | None
    image_status: Literal["APPROVED", "SOURCE", "NONE"]
    thumbnail_url: str | None = None
    is_pinned: bool = False


class SkuListPage(BaseModel):
    items: list[SkuListItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class SkuCatalogExportRequest(BaseModel):
    q: str = Field(default="", max_length=200)
    category_id: UUID | None = None
    statuses: list[Literal["DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"]] = Field(
        default_factory=list,
        max_length=4,
    )
    missing_images_only: bool = False
    sku_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_sku_ids(self) -> "SkuCatalogExportRequest":
        if len(self.sku_ids) != len(set(self.sku_ids)):
            raise ValueError("sku ids must be unique")
        return self


class SkuCreateItem(BaseModel):
    sku_code: str = Field(min_length=1, max_length=160)
    name: str | None = Field(default=None, max_length=500)
    option_values: dict[str, str | int | float | bool] = Field(default_factory=dict)
    barcode: str | None = Field(default=None, max_length=120)
    default_moq: Decimal | None = Field(default=None, ge=0)
    moq_unit: str | None = Field(default=None, max_length=32)
    packing_quantity: Decimal | None = Field(default=None, ge=0)
    weight: Decimal | None = Field(default=None, ge=0)
    weight_unit: str | None = Field(default=None, max_length=32)
    status: Literal["DRAFT", "ACTIVE", "INACTIVE"] = "DRAFT"

    @field_validator("sku_code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class SkuBatchCreateRequest(BaseModel):
    items: list[SkuCreateItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_codes(self) -> "SkuBatchCreateRequest":
        codes = [item.sku_code for item in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("SKU codes must be unique within the batch")
        return self


class SkuUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=500)
    option_values: dict[str, str | int | float | bool] | None = None
    barcode: str | None = Field(default=None, max_length=120)
    default_moq: Decimal | None = Field(default=None, ge=0)
    moq_unit: str | None = Field(default=None, max_length=32)
    weight: Decimal | None = Field(default=None, ge=0)
    weight_unit: str | None = Field(default=None, max_length=32)
    status: Literal["DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"] | None = None


class PublicCatalogOfferUpsertRequest(BaseModel):
    """Merchant-owned public selling facts, intentionally separate from supplier cost."""

    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    tags: list[str] = Field(default_factory=list, max_length=20)
    display_tag: str | None = Field(default=None, max_length=80)
    tag_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    publication_status: Literal["DRAFT", "PUBLISHED", "SUSPENDED"] = "DRAFT"
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_public_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("tag_color", mode="before")
    @classmethod
    def normalize_tag_color(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized.upper() if normalized else None

    @field_validator("display_tag", mode="before")
    @classmethod
    def normalize_display_tag(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("tags")
    @classmethod
    def normalize_public_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = value.strip()
            if not tag or tag.casefold() in seen:
                continue
            if len(tag) > 80:
                raise ValueError("public offer tags must not exceed 80 characters")
            seen.add(tag.casefold())
            normalized.append(tag)
        return normalized

    @model_validator(mode="after")
    def validate_public_validity(self) -> "PublicCatalogOfferUpsertRequest":
        if self.valid_to is not None and self.valid_from is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        if not self.tags:
            self.display_tag = None
            return self
        if self.display_tag is None:
            self.display_tag = self.tags[0]
            return self
        selected = next(
            (
                tag
                for tag in self.tags
                if tag.casefold() == self.display_tag.casefold()
            ),
            None,
        )
        if selected is None:
            raise ValueError("display_tag must be one of the public offer tags")
        self.display_tag = selected
        return self


class PublicCatalogOfferResponse(PublicCatalogOfferUpsertRequest):
    id: UUID
    sku_id: UUID
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ManualProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    product_code: str | None = Field(default=None, max_length=100)
    description: str | None = None
    category_id: UUID | None = None
    default_unit: str = Field(default="piece", min_length=1, max_length=32)
    image_url: str | None = Field(
        default=None,
        max_length=2048,
        pattern=r"^https?://[^\s]+$",
    )
    sku_code: str | None = Field(default=None, max_length=160)
    sku_name: str | None = Field(default=None, max_length=500)
    barcode: str | None = Field(default=None, max_length=120)
    default_moq: Decimal | None = Field(default=None, ge=0)
    moq_unit: str | None = Field(default=None, max_length=32)
    packing_quantity: Decimal | None = Field(default=None, ge=0)
    weight: Decimal | None = Field(default=None, ge=0)
    weight_unit: str | None = Field(default=None, max_length=32)
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="CNY", pattern=r"^[A-Za-z]{3}$")
    tags: list[str] = Field(default_factory=list, max_length=20)
    display_tag: str | None = Field(default=None, max_length=80)
    tag_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    publish_to_storefront: bool = True

    @field_validator("name")
    @classmethod
    def normalize_manual_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("product name must not be blank")
        return normalized

    @field_validator(
        "product_code",
        "description",
        "image_url",
        "sku_name",
        "barcode",
        "moq_unit",
        "weight_unit",
        "display_tag",
        mode="before",
    )
    @classmethod
    def normalize_optional_manual_text(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("default_unit")
    @classmethod
    def normalize_default_unit(cls, value: str) -> str:
        return value.strip() or "piece"

    @field_validator("sku_code", mode="before")
    @classmethod
    def normalize_manual_sku_code(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @field_validator("currency")
    @classmethod
    def normalize_manual_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("tag_color", mode="before")
    @classmethod
    def normalize_manual_tag_color(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized.upper() if normalized else None

    @field_validator("tags")
    @classmethod
    def normalize_manual_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            tag = value.strip()
            key = tag.casefold()
            if not tag or key in seen:
                continue
            if len(tag) > 80:
                raise ValueError("product tags must not exceed 80 characters")
            seen.add(key)
            normalized.append(tag)
        return normalized

    @model_validator(mode="after")
    def normalize_manual_display_tag(self) -> "ManualProductCreateRequest":
        if not self.tags:
            self.display_tag = None
            return self
        if self.display_tag is None:
            self.display_tag = self.tags[0]
            return self
        selected = next(
            (tag for tag in self.tags if tag.casefold() == self.display_tag.casefold()),
            None,
        )
        if selected is None:
            raise ValueError("display_tag must be one of the product tags")
        self.display_tag = selected
        return self


class AttributeDefinitionCreateRequest(BaseModel):
    category_id: UUID | None = None
    attribute_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")
    display_name: str = Field(min_length=1, max_length=200)
    data_type: Literal["TEXT", "NUMBER", "BOOLEAN", "ENUM"]
    unit_code: str | None = Field(default=None, max_length=32)
    enum_values: list[str] | None = None
    is_required: bool = False
    is_variant: bool = False
    is_filterable: bool = True
    is_matchable: bool = True

    @model_validator(mode="after")
    def validate_enum(self) -> "AttributeDefinitionCreateRequest":
        if self.data_type == "ENUM" and not self.enum_values:
            raise ValueError("enum_values are required for ENUM")
        return self


class AttributeDefinitionResponse(AttributeDefinitionCreateRequest):
    id: UUID
    status: str
    version: int


class CategoryCreateRequest(BaseModel):
    parent_id: UUID | None = None
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = Field(default=0, ge=0)
    display_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("code")
    @classmethod
    def normalize_category_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_category_name(cls, value: str) -> str:
        normalized = value.strip()
        if "/" in normalized or "／" in normalized:
            raise ValueError("category name must be a single hierarchy segment")
        return normalized

    @field_validator("display_color", mode="before")
    @classmethod
    def normalize_display_color(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized.upper() if normalized else None


class CategoryResponse(CategoryCreateRequest):
    id: UUID
    path: str | None
    status: str
    version: int
    cover_source: Literal["NONE", "UPLOAD", "PRODUCT"] = "NONE"
    cover_product_id: UUID | None = None
    cover_product_name: str | None = None
    cover_image_url: str | None = None
    uploaded_cover_image_url: str | None = None
    cover_product_image_url: str | None = None


class CategoryUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = Field(default=0, ge=0)
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    display_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    cover_source: Literal["NONE", "UPLOAD", "PRODUCT"] | None = None
    cover_product_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_category_name(cls, value: str) -> str:
        normalized = value.strip()
        if "/" in normalized or "／" in normalized:
            raise ValueError("category name must be a single hierarchy segment")
        return normalized

    @field_validator("display_color", mode="before")
    @classmethod
    def normalize_display_color(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized.upper() if normalized else None

    @model_validator(mode="after")
    def validate_cover(self) -> "CategoryUpdateRequest":
        if self.cover_source == "PRODUCT" and self.cover_product_id is None:
            raise ValueError("cover_product_id is required for a product cover")
        if self.cover_source != "PRODUCT" and self.cover_product_id is not None:
            raise ValueError("cover_product_id is only allowed for a product cover")
        return self


class CategoryReorderItem(BaseModel):
    id: UUID
    expected_version: int = Field(ge=1)


class CategoryReorderRequest(BaseModel):
    items: list[CategoryReorderItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_category_ids(self):
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("category ids must be unique")
        return self


class CategoryLayoutResponse(BaseModel):
    all_products_position: int = Field(ge=0)
    root_category_count: int = Field(ge=0)
    category_showcase_enabled: bool = True


class CategoryLayoutUpdateRequest(BaseModel):
    all_products_position: int = Field(ge=0, le=500)
    category_showcase_enabled: bool = True


class CategoryImportResponse(BaseModel):
    processed_rows: int = Field(ge=1)
    primary_created: int = Field(ge=0)
    secondary_created: int = Field(ge=0)
    primary_existing: int = Field(ge=0)
    secondary_existing: int = Field(ge=0)
    duplicate_rows_ignored: int = Field(ge=0)
    blank_rows_ignored: int = Field(ge=0)


class CategoryDeleteImpactResponse(BaseModel):
    category_id: UUID
    category_name: str
    is_primary: bool
    child_category_count: int = Field(ge=0)
    affected_product_count: int = Field(ge=0)
    attribute_definition_count: int = Field(ge=0)
    attribute_value_count: int = Field(ge=0)


class CategoryDeleteResponse(BaseModel):
    deleted_category_count: int = Field(ge=1)
    unclassified_product_count: int = Field(ge=0)
    deleted_attribute_definition_count: int = Field(ge=0)
    detached_attribute_value_count: int = Field(ge=0)
    all_products_position: int = Field(ge=0)


class SupplierPriceCreateRequest(BaseModel):
    supplier_product_id: UUID
    sku_id: UUID | None = None
    min_quantity: Decimal = Field(ge=0)
    max_quantity: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    unit_code: str = Field(min_length=1, max_length=32)
    incoterm: str | None = Field(default=None, max_length=20)
    tax_status: str | None = Field(default=None, max_length=40)
    valid_from: datetime
    valid_to: datetime | None = None
    source_evidence_id: UUID | None = None
    supersedes_price_id: UUID | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_ranges(self) -> "SupplierPriceCreateRequest":
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity must be greater than or equal to min_quantity")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self


class SupplierPriceResponse(SupplierPriceCreateRequest):
    id: UUID
    product_id: UUID
    supplier_id: str
    supplier_name: str
    status: str
    price_validity: Literal["VALID", "EXPIRING", "EXPIRED", "UNKNOWN"]
    confirmed_by_membership_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime


class ProductAttributeResponse(BaseModel):
    id: UUID
    definition_id: UUID | None
    key: str
    value: Any
    unit_code: str | None
    review_status: str


class ProductImageResponse(BaseModel):
    id: UUID
    product_id: UUID
    url: str
    original_filename: str | None
    content_type: str
    byte_size: int = Field(ge=0)
    width: int | None
    height: int | None
    image_role: str
    approval_status: str
    created_at: datetime


class ProductAuditEventResponse(BaseModel):
    id: UUID
    entity_type: str
    entity_id: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    actor_membership_id: UUID
    occurred_at: datetime


class ProductDetail(ProductCard):
    description: str | None
    default_unit: str | None
    attributes: list[ProductAttributeResponse]
    skus: list[SkuResponse]
    sources: list[ProductOfferSummary]
    activity: list[ProductAuditEventResponse]


class ReviewQueueField(BaseModel):
    key: str
    label: str
    source: str
    normalized: str
    confidence: Decimal | None


class ProductReviewQueueItem(BaseModel):
    id: str
    task_id: UUID
    candidate_group_key: str
    status: Literal["pending", "approved", "rejected"]
    name: str
    model: str
    supplier: str
    source: str
    location: str
    image_status: Literal["SOURCE"] = "SOURCE"
    fields: list[ReviewQueueField]
    applied_product_id: UUID | None = None


class SkuBatchDeleteRequest(BaseModel):
    sku_ids: list[UUID] = Field(min_length=1, max_length=500)


class ProductDeleteAllRequest(BaseModel):
    password: SecretStr


class ProductDeleteAllJobResponse(BaseModel):
    id: UUID
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    stage: Literal[
        "QUEUED",
        "COUNTING",
        "HIDING_OFFERS",
        "ARCHIVING_SKUS",
        "ARCHIVING_PRODUCTS",
        "FINALIZING",
        "COMPLETED",
        "FAILED",
    ]
    progress: int = Field(ge=0, le=100)
    total_products: int = Field(ge=0)
    total_skus: int = Field(ge=0)
    deleted_product_count: int = Field(ge=0)
    deleted_sku_count: int = Field(ge=0)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SkuBatchUpdateStatusRequest(BaseModel):
    sku_ids: list[UUID] = Field(min_length=1, max_length=500)
    status: Literal["DRAFT", "ACTIVE", "INACTIVE", "ARCHIVED"]


class SkuBatchUpdateCategoryRequest(BaseModel):
    sku_ids: list[UUID] = Field(min_length=1, max_length=500)
    category_id: UUID | None = None


class SkuBatchUpdatePinnedRequest(BaseModel):
    sku_ids: list[UUID] = Field(min_length=1, max_length=500)
    pinned: bool


class SkuBatchOperationResponse(BaseModel):
    success_count: int
    failed_count: int
    total_count: int
    failed_items: list[dict[str, Any]] = Field(default_factory=list)
    applied_product_version: int | None = None
    affected_product_count: int | None = None
