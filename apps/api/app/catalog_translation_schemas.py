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


class CatalogTranslationJobStartRequest(BaseModel):
    target_locale: Literal["en-US"] = "en-US"
    mode: Literal["INCREMENTAL", "FULL_REBUILD"] = "INCREMENTAL"
    confirm_full_rebuild: bool = False


class CatalogTranslationJobResponse(BaseModel):
    id: UUID
    source_locale: str
    target_locale: str
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    total_skus: int = Field(ge=0)
    processed_skus: int = Field(ge=0)
    failed_skus: int = Field(ge=0)
    progress_percent: float = Field(ge=0, le=100)
    current_sku_id: UUID | None = None
    current_sku_name: str | None = None
    provider: str
    provider_version: str
    failure_details: list[CatalogTranslationFailure] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CatalogTranslationStatusResponse(BaseModel):
    source_locale: str
    target_locale: str
    provider: str
    provider_version: str
    provider_configured: bool
    total_skus: int = Field(ge=0)
    translated_skus: int = Field(ge=0)
    stale_skus: int = Field(ge=0)
    pending_skus: int = Field(ge=0)
    available_locales: list[str]
    latest_job: CatalogTranslationJobResponse | None = None
