from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    SCANNING = "scanning"
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    PUBLISHED = "published"
    FAILED = "failed"


class Supplier(BaseModel):
    id: str
    name: str
    category: str
    active_skus: int
    review_count: int
    freshness: str
    health: str


class ImportJob(BaseModel):
    id: str
    filename: str
    supplier: str
    source_type: str = "UNKNOWN"
    detected_type: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    products: int = 0
    warnings: int = 0
    created_at: str
    parser: str = "manual_review"
    extension_matches: bool = True
    error_message: str | None = None
    warning_messages: list[str] = Field(default_factory=list)
    result_details: dict[str, object] = Field(default_factory=dict)


class SupplierFileImportResponse(ImportJob):
    ai_task_id: str | None = None
    candidate_fields: int = 0
    candidate_status: str | None = None
    candidate_idempotent: bool = False


class CatalogImportBatchCreateRequest(BaseModel):
    expected_file_count: int = Field(ge=1, le=100)


class CatalogImportBatchCategory(BaseModel):
    id: str
    name: str
    sku_count: int = Field(ge=0)


class CatalogImportBatch(BaseModel):
    id: UUID
    status: str
    expected_file_count: int
    file_count: int
    remaining_sku_count: int
    created_at: str
    jobs: list[ImportJob] = Field(default_factory=list)
    categories: list[CatalogImportBatchCategory] = Field(default_factory=list)


class CatalogImportBatchRollbackRequest(BaseModel):
    category_id: str | None = None


class CatalogImportBatchRollbackResponse(BaseModel):
    batch_id: UUID
    status: str
    deleted_sku_count: int = Field(ge=0)
    archived_product_count: int = Field(ge=0)
    removed_image_count: int = Field(ge=0)
    deleted_storage_image_count: int = Field(ge=0)
    preserved_external_image_count: int = Field(ge=0)
    retained_shared_image_count: int = Field(ge=0)
    storage_delete_failures: int = Field(ge=0)
    remaining_sku_count: int = Field(ge=0)


class ProductCandidateEvidence(BaseModel):
    source_file_id: str | None
    location: dict[str, object]
    raw_value_hash: str | None


class ProductCandidateDecisionSummary(BaseModel):
    id: str
    action: str
    status: str
    product_id: str | None = None
    applied_product_version: int | None = None
    reviewed_by_membership_id: str
    reviewed_at: str


class ProductFieldCandidate(BaseModel):
    id: str
    task_id: str
    candidate_group_key: str
    candidate_index: int
    field_key: str
    raw_value: str
    normalized_value: dict[str, object]
    normalized_unit: str | None = None
    confidence: Decimal | None
    validation_status: str
    review_status: str
    warnings: list[str] = Field(default_factory=list)
    normalization_rule_version: str
    normalization_trace: list[dict[str, object]] = Field(default_factory=list)
    evidence: ProductCandidateEvidence
    latest_decision: ProductCandidateDecisionSummary | None = None


class ProductCandidateApproveRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    confirmed_values: dict[str, str] = Field(min_length=1)
    activate: bool
    target_product_id: UUID | None = None
    expected_product_version: int | None = Field(default=None, ge=1)
    product_code: str | None = Field(default=None, max_length=100)
    change_reason: str | None = Field(default=None, max_length=500)


class ProductCandidateApproveResponse(BaseModel):
    decision_id: str
    product_id: str
    product_version: int
    outbox_event_id: str
    outbox_status: str
    idempotent: bool


class ProductCandidateRejectRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class ProductCandidateRejectResponse(BaseModel):
    decision_id: str
    status: str
    idempotent: bool


class Product(BaseModel):
    id: str
    name: str
    model: str
    category: str
    supplier: str
    price: Decimal
    currency: str
    moq: int
    updated: str
    image_status: str
    tags: list[str]


class ReviewField(BaseModel):
    key: str
    label: str
    source: str
    normalized: str
    confidence: float = Field(ge=0, le=1)


class ReviewItem(BaseModel):
    id: str
    job_id: str = ""
    status: str = "pending"
    name: str
    model: str
    category: str = "待分类"
    supplier: str
    source: str
    location: str
    image_status: str
    fields: list[ReviewField]


class ReviewItemUpdate(BaseModel):
    normalized_values: dict[str, str] = Field(default_factory=dict)


class ReviewApprovalResponse(BaseModel):
    id: str
    status: str
    image_status: str


Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]


class CostItem(BaseModel):
    name: str
    amount_per_unit: Money


class PriceCalculationRequest(BaseModel):
    purchase_price: Money
    quantity: int = Field(gt=0, le=10_000_000)
    target_margin_rate: Decimal = Field(gt=0, lt=1)
    cost_items: list[CostItem] = Field(default_factory=list)
    currency: str = Field(default="CNY", min_length=3, max_length=3)


class PriceCalculationResponse(BaseModel):
    currency: str
    quantity: int
    purchase_price: Decimal
    unit_cost: Decimal
    suggested_unit_price: Decimal
    total_cost: Decimal
    quotation_total: Decimal
    gross_profit: Decimal
    gross_margin_rate: Decimal
    formula: str


class FileDetectionResponse(BaseModel):
    filename: str
    extension: str
    detected_type: str
    extension_matches: bool
    parser: str
    warning: str | None = None
