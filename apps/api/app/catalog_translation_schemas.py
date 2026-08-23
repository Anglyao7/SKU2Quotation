from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    sku_ids: list[UUID] = Field(default_factory=list)
    sku_refs: list[dict[str, str]] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    total_skus: int = Field(default=0, ge=0)
    processed_skus: int = Field(default=0, ge=0)
    failed_skus: int = Field(default=0, ge=0)
    request_started_at: datetime | None = None
    first_byte_at: datetime | None = None
    completed_at: datetime | None = None
    response_time_ms: int | None = Field(default=None, ge=0)
    error_message: str | None = None
    attempts: list[CatalogTranslationBatchAttemptResponse] = Field(
        default_factory=list
    )


class CatalogTranslationJobStartRequest(BaseModel):
    target_locale: Literal["en-US", "es", "tr", "ar", "ja", "ko", "pt"] = "en-US"
    mode: Literal["INCREMENTAL", "FULL_REBUILD"] = "INCREMENTAL"
    confirm_full_rebuild: bool = False


class CatalogTranslationProductRetryRequest(BaseModel):
    """Request a fresh translation for every public SKU of one product."""

    target_locale: Literal["en-US", "es", "tr", "ar", "ja", "ko", "pt"] = "en-US"


class CatalogTranslationJobResponse(BaseModel):
    id: UUID
    source_locale: str
    target_locale: str
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
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
