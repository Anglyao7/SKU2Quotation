from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


CatalogTargetLocale = Literal["en-US", "es", "tr", "ar", "ja", "ko", "pt"]


class CatalogTranslationFailure(BaseModel):
    sku_id: UUID | None = None
    sku_code: str | None = None
    name: str | None = None
    message: str


class CatalogTranslationBatchAttemptResponse(BaseModel):
    id: UUID
    attempt_no: int = Field(ge=1)
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    sku_ids: list[UUID] = Field(default_factory=list)
    sku_refs: list[dict[str, str]] = Field(default_factory=list)
    request_started_at: datetime
    first_byte_at: datetime | None = None
    completed_at: datetime | None = None
    first_byte_latency_ms: int | None = Field(default=None, ge=0)
    response_time_ms: int | None = Field(default=None, ge=0)
    processed_skus: int = Field(default=0, ge=0)
    failed_skus: int = Field(default=0, ge=0)
    error_message: str | None = None


class CatalogTranslationBatchResponse(BaseModel):
    id: UUID
    sequence_no: int = Field(ge=1)
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
    item_kind: Literal["SKU", "TEXT"] = "SKU"
    request_id: str | None = None
    source_locale: str | None = None
    sku_ids: list[UUID] = Field(default_factory=list)
    sku_refs: list[dict[str, str]] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    total_skus: int = Field(default=0, ge=0)
    processed_skus: int = Field(default=0, ge=0)
    failed_skus: int = Field(default=0, ge=0)
    total_items: int = Field(default=0, ge=0)
    processed_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    request_started_at: datetime | None = None
    first_byte_at: datetime | None = None
    completed_at: datetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None
    attempts: list[CatalogTranslationBatchAttemptResponse] = Field(
        default_factory=list
    )


class CatalogTranslationJobStartRequest(BaseModel):
    target_locale: CatalogTargetLocale = "en-US"
    mode: Literal["INCREMENTAL", "FULL_REBUILD"] = "INCREMENTAL"
    execution_mode: Literal["REALTIME", "QWEN_BATCH"] | None = None
    confirm_full_rebuild: bool = False


class CatalogTranslationProductRetryRequest(BaseModel):
    """Request a fresh translation for every public SKU of one product."""

    target_locale: CatalogTargetLocale = "en-US"


class CatalogLocalizedProductContent(BaseModel):
    name: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=100_000)
    category_label: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    display_tag: str | None = Field(default=None, max_length=500)
    specifications: dict[str, str] = Field(default_factory=dict)
    option_labels: dict[str, str] = Field(default_factory=dict)
    option_values: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("translated product name is required")
        return normalized

    @field_validator("description", "category_label", "display_tag", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return list(
            dict.fromkeys(
                normalized
                for item in value
                if (normalized := str(item).strip())
            )
        )[:100]

    @field_validator("specifications", "option_labels", "option_values", mode="before")
    @classmethod
    def normalize_mappings(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            translated = str(raw_value).strip()
            if key and translated:
                result[key] = translated
        return result


class CatalogLocalizedSkuContent(BaseModel):
    sku_id: UUID
    name: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=100_000)
    category_label: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    display_tag: str | None = Field(default=None, max_length=500)
    specification: str | None = Field(default=None, max_length=1000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("translated SKU name is required")
        return normalized

    @field_validator(
        "description",
        "category_label",
        "display_tag",
        "specification",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return list(
            dict.fromkeys(
                normalized
                for item in value
                if (normalized := str(item).strip())
            )
        )[:100]


class CatalogTranslationProductListItem(BaseModel):
    id: UUID
    product_code: str | None = None
    source_name: str
    source_category: str | None = None
    translated_name: str | None = None
    translated_category: str | None = None
    status: Literal["TRANSLATED", "MISSING", "STALE", "MANUAL"]
    sku_count: int = Field(ge=0)


class CatalogTranslationProductListResponse(BaseModel):
    items: list[CatalogTranslationProductListItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
    package_version: int | None = Field(default=None, ge=1)


class CatalogTranslationSkuDetail(BaseModel):
    id: UUID
    sku_code: str
    source_hash: str = Field(min_length=64, max_length=64)
    status: Literal["TRANSLATED", "MISSING", "STALE", "MANUAL"]
    source: CatalogLocalizedSkuContent
    translation: CatalogLocalizedSkuContent


class CatalogTranslationProductDetail(BaseModel):
    id: UUID
    product_code: str | None = None
    source_hash: str = Field(min_length=64, max_length=64)
    target_locale: CatalogTargetLocale
    status: Literal["TRANSLATED", "MISSING", "STALE", "MANUAL"]
    package_version: int | None = Field(default=None, ge=1)
    source: CatalogLocalizedProductContent
    translation: CatalogLocalizedProductContent
    skus: list[CatalogTranslationSkuDetail] = Field(default_factory=list)


class CatalogTranslationProductUpdateRequest(BaseModel):
    target_locale: CatalogTargetLocale
    source_hash: str = Field(min_length=64, max_length=64)
    sku_source_hashes: dict[UUID, str] = Field(default_factory=dict)
    product: CatalogLocalizedProductContent
    skus: list[CatalogLocalizedSkuContent] = Field(
        default_factory=list,
        max_length=5000,
    )

    @field_validator("sku_source_hashes")
    @classmethod
    def validate_sku_source_hashes(cls, value: dict[UUID, str]) -> dict[UUID, str]:
        if any(len(source_hash) != 64 for source_hash in value.values()):
            raise ValueError("SKU source hashes must be SHA-256 values")
        return value


class CatalogTranslationJobResponse(BaseModel):
    id: UUID
    source_locale: str
    target_locale: str
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    execution_mode: Literal["REALTIME", "QWEN_BATCH"] = "REALTIME"
    status: Literal["QUEUED", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED"]
    stage: Literal[
        "QUEUED",
        "PREPARING",
        "TRANSLATING",
        "PACKAGING",
        "UPLOADING",
        "PAUSED",
        "PUBLISHED",
        "FAILED",
    ] = "QUEUED"
    total_skus: int = Field(ge=0)
    processed_skus: int = Field(ge=0)
    failed_skus: int = Field(ge=0)
    remaining_skus: int = Field(ge=0)
    progress_percent: float = Field(ge=0, le=100)
    current_sku_id: UUID | None = None
    current_sku_name: str | None = None
    failure_details: list[CatalogTranslationFailure] = Field(default_factory=list)
    error_message: str | None = None
    package_version: int | None = Field(default=None, ge=1)
    package_published: bool = False
    package_byte_size: int | None = Field(default=None, ge=0)
    source_cutoff_at: datetime | None = None
    pause_requested: bool = False
    pause_requested_at: datetime | None = None
    paused_at: datetime | None = None
    resumable: bool = False
    checkpoint_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    batch_count: int = Field(default=0, ge=0)
    completed_batch_count: int = Field(default=0, ge=0)
    failed_batch_count: int = Field(default=0, ge=0)
    external_batch_id: str | None = None
    external_batch_status: str | None = None
    external_total_requests: int = Field(default=0, ge=0)
    external_completed_requests: int = Field(default=0, ge=0)
    external_failed_requests: int = Field(default=0, ge=0)
    translation_total_values: int = Field(default=0, ge=0)
    translation_processed_values: int = Field(default=0, ge=0)
    translation_processed_skus: int = Field(default=0, ge=0)
    finalization_total_values: int = Field(default=0, ge=0)
    finalization_processed_values: int = Field(default=0, ge=0)


class CatalogLanguagePackResponse(BaseModel):
    source_locale: str
    target_locale: str
    version: int = Field(ge=1)
    download_url: str
    content_sha256: str = Field(min_length=64, max_length=64)
    content_encoding: str = "gzip"
    byte_size: int = Field(ge=0)
    product_count: int = Field(ge=0)
    sku_count: int = Field(ge=0)
    category_count: int = Field(ge=0)
    source_cutoff_at: datetime
    published_at: datetime
    last_full_translation_at: datetime | None = None


class CatalogTranslationStatusResponse(BaseModel):
    source_locale: str
    target_locale: str
    provider_configured: bool
    total_skus: int = Field(ge=0)
    translated_skus: int = Field(ge=0)
    stale_skus: int = Field(ge=0)
    pending_skus: int = Field(ge=0)
    package_outdated: bool = False
    package_storage_configured: bool
    available_locales: list[str]
    package: CatalogLanguagePackResponse | None = None
    latest_job: CatalogTranslationJobResponse | None = None
