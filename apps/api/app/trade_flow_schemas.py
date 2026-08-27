from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CustomerCreateRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=300)
    customer_code: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    language: str = Field(default="en", max_length=20)
    default_currency: str = Field(default="USD", min_length=3, max_length=3)


class CustomerResponse(BaseModel):
    id: UUID
    customer_code: str
    company_name: str
    country_code: str | None
    language: str
    default_currency: str
    status: str


class InquiryItemCreate(BaseModel):
    requirement: str = Field(min_length=1, max_length=2000)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_code: str | None = Field(default=None, max_length=32)
    target_price: Decimal | None = Field(default=None, ge=0)
    target_currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_search_id: UUID | None = None


class InquiryCreateRequest(BaseModel):
    customer_id: UUID | None = None
    temporary_customer_name: str | None = Field(default=None, max_length=300)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    language: str = Field(default="en", max_length=20)
    source_type: str = Field(default="MANUAL", max_length=30)
    items: list[InquiryItemCreate] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def customer_context(self):
        if not self.customer_id and not self.temporary_customer_name:
            raise ValueError("customer_id or temporary_customer_name is required")
        return self


class InquiryItemResponse(BaseModel):
    id: UUID
    line_number: int
    raw_requirement: str
    normalized_requirement: dict[str, object]
    quantity: Decimal | None
    unit_code: str | None
    target_price: Decimal | None
    target_currency: str | None
    image_search_id: UUID | None
    status: str
    version: int


class InquiryResponse(BaseModel):
    id: UUID
    inquiry_number: str
    customer_id: UUID | None
    temporary_customer_name: str | None
    currency: str
    language: str
    status: str
    version: int
    # A parent account may inspect a child-owned inquiry, but cannot advance
    # or edit it.  Keeping this marker in the response lets the UI present the
    # same operator workspace without accidentally rendering mutation actions.
    read_only: bool = False
    items: list[InquiryItemResponse]


class InquiryItemConfirmRequest(BaseModel):
    expected_version: int = Field(ge=1)
    normalized_requirement: dict[str, str | int | float | bool] = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit_code: str = Field(min_length=1, max_length=32)


class MatchResultResponse(BaseModel):
    id: UUID
    inquiry_item_id: UUID
    product_id: UUID
    sku_id: UUID | None
    supplier_product_id: UUID | None
    product_version: int
    rank: int
    total_score: float
    score_breakdown: dict[str, object]
    reasons: list[str]
    gaps: list[str]
    evidence: list[dict[str, object]]
    ranking_version: str
    status: str


class InquiryMatchResponse(BaseModel):
    inquiry_id: UUID
    status: str
    ranking_version: str
    candidates: dict[str, list[MatchResultResponse]]
    read_only: bool = False


class CandidateSelectRequest(BaseModel):
    match_result_id: UUID


class QuotationCreateRequest(BaseModel):
    target_margin_rate: Decimal = Field(gt=0, lt=1)
    expires_in_days: int = Field(default=30, ge=1, le=365)


class QuotationItemResponse(BaseModel):
    id: UUID
    inquiry_item_id: UUID
    product_id: UUID
    sku_id: UUID | None
    # Supplier sources are owner-only.  A child account receives a redacted
    # quotation item, while the parent can still inspect the full source.
    supplier_product_id: UUID | None
    product_snapshot: dict[str, object]
    source_snapshot: dict[str, object]
    quantity: Decimal
    unit_code: str
    unit_cost: Decimal | None
    target_margin_rate: Decimal | None
    unit_price: Decimal
    line_total: Decimal
    warnings: list[str]


class QuotationVersionSummary(BaseModel):
    version_number: int
    total_amount: Decimal
    currency: str
    rule_version: str
    content_hash: str
    approval_status: str
    created_at: datetime


class QuotationResponse(BaseModel):
    id: UUID
    quotation_number: str
    inquiry_id: UUID
    customer_id: UUID
    currency: str
    status: str
    current_version: int
    total_amount: Decimal
    expires_at: datetime | None
    approval_status: str
    read_only: bool = False
    version_hash: str
    items: list[QuotationItemResponse]
    versions: list[QuotationVersionSummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class QuotationSummary(BaseModel):
    id: UUID
    quotation_number: str
    customer_name: str
    currency: str
    status: str
    current_version: int
    total_amount: Decimal
    updated_at: datetime
    read_only: bool = False


class QuotationDecisionRequest(BaseModel):
    decision: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=500)


class QuotationItemRevision(BaseModel):
    item_id: UUID
    quantity: Decimal = Field(gt=0)
    target_margin_rate: Decimal = Field(gt=0, lt=1)


class QuotationRevisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    change_reason: str = Field(min_length=3, max_length=500)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    items: list[QuotationItemRevision] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_items(self):
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("items must not contain duplicate item_id values")
        return self
