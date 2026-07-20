from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DashboardMetric(BaseModel):
    key: str
    label: str
    value: int | float
    unit: str | None = None
    status: str = "AVAILABLE"
    destination: str


class DashboardImport(BaseModel):
    id: str
    filename: str
    supplier_name: str
    status: str
    progress: int
    products_count: int
    warnings_count: int
    created_at: datetime


class DashboardDataHealth(BaseModel):
    score: int = Field(ge=0, le=100)
    active_products: int
    approved_image_coverage: float = Field(ge=0, le=1)
    supplier_source_coverage: float = Field(ge=0, le=1)
    valid_price_coverage: float = Field(ge=0, le=1)


class DashboardResponse(BaseModel):
    generated_at: datetime
    data_scope: str
    metrics: list[DashboardMetric]
    recent_imports: list[DashboardImport]
    data_health: DashboardDataHealth | None


class SupplierScoreSummary(BaseModel):
    overall_score: Decimal | None
    quality_score: Decimal | None
    price_score: Decimal | None
    delivery_score: Decimal | None
    response_score: Decimal | None
    risk_score: Decimal | None
    sample_size: int
    method_version: str
    calculated_at: datetime


class SupplierProfileSummary(BaseModel):
    id: str
    supplier_code: str
    name: str
    category: str
    category_summary: str | None
    country_code: str | None
    website: str | None
    status: str
    risk_level: str
    health: str
    version: int
    active_products: int
    active_skus: int
    pending_reviews: int
    valid_prices: int
    expired_prices: int
    latest_import_at: datetime | None
    updated_at: datetime
    latest_score: SupplierScoreSummary | None


class SupplierCreateRequest(BaseModel):
    supplier_code: str = Field(min_length=2, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=300)
    category: str = Field(default="待分类", min_length=1, max_length=200)
    country_code: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    website: str | None = Field(default=None, max_length=1000)

    @field_validator("supplier_code")
    @classmethod
    def normalize_supplier_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name", "category")
    @classmethod
    def trim_required_supplier_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None

    @field_validator("website")
    @classmethod
    def normalize_website(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SupplierSourceSummary(BaseModel):
    supplier_product_id: UUID
    product_id: UUID
    product_code: str
    product_name: str
    sku_id: UUID | None
    supplier_sku: str | None
    moq: Decimal | None
    moq_unit: str | None
    lead_time_days: int | None
    status: str
    unit_price: Decimal | None
    currency: str | None
    price_valid_to: datetime | None
    price_validity: str


class SupplierImportSummary(BaseModel):
    id: str
    filename: str
    status: str
    products_count: int
    warnings_count: int
    created_at: datetime


class SupplierProfileDetail(SupplierProfileSummary):
    sources: list[SupplierSourceSummary]
    recent_imports: list[SupplierImportSummary]
