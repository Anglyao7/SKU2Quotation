from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


QuoteTemplateField = Literal[
    "serial_number",
    "sku_code",
    "product_name",
    "description",
    "specification",
    "category",
    "tags",
    "product_image",
    "quantity",
    "unit_code",
    "packing_quantity",
    "carton_dimensions",
    "gross_weight",
    "carton_volume",
    "minimum_order_quantity",
    "unit_price",
    "line_total",
    "total_volume",
    "total_gross_weight",
    "currency",
    "quote_number",
    "quote_date",
    "customer_name",
    "customer_company",
    "customer_email",
    "customer_phone",
    "notes",
]


# Merchant-uploaded Excel templates describe the product-detail region only.
# Quote-level metadata (merchant, quote number, customer, date and contacts)
# is always rendered by the system so every exported quotation remains a
# complete, recognizable business document.
QUOTE_PRODUCT_TEMPLATE_FIELDS = frozenset(
    {
        "serial_number",
        "sku_code",
        "product_name",
        "description",
        "specification",
        "category",
        "tags",
        "product_image",
        "quantity",
        "unit_code",
        "packing_quantity",
        "carton_dimensions",
        "gross_weight",
        "carton_volume",
        "minimum_order_quantity",
        "unit_price",
        "line_total",
        "total_volume",
        "total_gross_weight",
        "currency",
    }
)


class QuoteExcelColumn(BaseModel):
    key: str = Field(min_length=1, max_length=3)
    index: int = Field(ge=1, le=16_384)
    header: str = Field(max_length=500)
    samples: list[str] = Field(default_factory=list, max_length=5)
    suggested_field: QuoteTemplateField | None = None
    mapped_field: QuoteTemplateField | None = None


class QuoteExcelTemplateResponse(BaseModel):
    id: UUID
    name: str
    original_filename: str
    byte_size: int
    sheet_names: list[str]
    sheet_name: str
    header_row: int
    data_start_row: int
    data_end_row: int
    columns: list[QuoteExcelColumn]
    column_mappings: dict[str, QuoteTemplateField]
    is_default: bool
    is_ready: bool
    version: int
    created_at: datetime
    updated_at: datetime


class QuoteExcelTemplateListResponse(BaseModel):
    items: list[QuoteExcelTemplateResponse]
    total: int


class QuoteExcelTemplateUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    column_mappings: dict[str, QuoteTemplateField] = Field(default_factory=dict)
    is_default: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("column_mappings", mode="before")
    @classmethod
    def normalize_mapping_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {
            str(key).strip().upper(): mapped
            for key, mapped in value.items()
            if str(key).strip()
        }

    @model_validator(mode="after")
    def default_requires_mapping(self) -> "QuoteExcelTemplateUpdateRequest":
        invalid_fields = sorted(
            set(self.column_mappings.values()) - QUOTE_PRODUCT_TEMPLATE_FIELDS
        )
        if invalid_fields:
            raise ValueError(
                "quote templates only map product-detail fields: "
                + ", ".join(invalid_fields)
            )
        if self.is_default and not self.column_mappings:
            raise ValueError("a default quote template requires at least one mapped column")
        return self


class QuoteExcelTemplateReparseRequest(BaseModel):
    sheet_name: str = Field(min_length=1, max_length=200)
    header_row: int = Field(ge=1, le=100_000)

    @field_validator("sheet_name", mode="before")
    @classmethod
    def normalize_sheet_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class QuoteExcelTemplateRenderSpec(BaseModel):
    object_key: str
    sheet_name: str
    header_row: int
    data_start_row: int
    data_end_row: int
    columns: list[QuoteExcelColumn]
    column_mappings: dict[str, QuoteTemplateField]
