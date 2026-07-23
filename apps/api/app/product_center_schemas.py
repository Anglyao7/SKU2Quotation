from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


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
    public_price: Decimal | None
    public_currency: str | None
    public_offer_status: Literal["DRAFT", "PUBLISHED", "SUSPENDED"] | None
    status: str
    version: int
    updated_at: datetime
    image_status: Literal["APPROVED", "SOURCE", "NONE"]


class SkuListPage(BaseModel):
    items: list[SkuListItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class SkuCreateItem(BaseModel):
    sku_code: str = Field(min_length=1, max_length=160)
    name: str | None = Field(default=None, max_length=500)
    option_values: dict[str, str | int | float | bool] = Field(default_factory=dict)
    barcode: str | None = Field(default=None, max_length=120)
    default_moq: Decimal | None = Field(default=None, ge=0)
    moq_unit: str | None = Field(default=None, max_length=32)
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

    unit_price: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    tags: list[str] = Field(default_factory=list, max_length=20)
    publication_status: Literal["DRAFT", "PUBLISHED", "SUSPENDED"] = "DRAFT"
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_public_currency(cls, value: str) -> str:
        return value.upper()

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
        return self


class PublicCatalogOfferResponse(PublicCatalogOfferUpsertRequest):
    id: UUID
    sku_id: UUID
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


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

    @field_validator("code")
    @classmethod
    def normalize_category_code(cls, value: str) -> str:
        return value.strip().upper()


class CategoryResponse(CategoryCreateRequest):
    id: UUID
    path: str | None
    status: str
    version: int


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
    applied_product_version: int | None = None
