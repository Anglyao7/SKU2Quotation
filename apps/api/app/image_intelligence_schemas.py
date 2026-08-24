from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr


class ImageProjectionResponse(BaseModel):
    product_id: UUID
    product_image_id: UUID
    quality_score: float
    labels: list[dict[str, object]]
    risks: list[dict[str, object]]
    idempotent: bool


class ImageSearchResult(BaseModel):
    product_id: UUID
    product_image_id: UUID
    product_name: str
    product_code: str | None
    visual_similarity: float = Field(ge=-1, le=1)
    classification: Literal["VISUALLY_SIMILAR", "POSSIBLE_SAME_ITEM"]
    conflicts: list[str]


class ImageSearchResponse(BaseModel):
    id: UUID
    status: Literal["COMPLETED", "NO_RELIABLE_MATCH"]
    expires_at: datetime
    warnings: list[str]
    results: list[ImageSearchResult]


class ImageEmbeddingSettingsResponse(BaseModel):
    source: Literal["database", "environment", "deterministic", "unconfigured"]
    provider: str
    enabled: bool
    base_url: str | None = None
    model_name: str
    model_version: str
    dimensions: int
    timeout_seconds: int = Field(ge=1, le=120)
    max_retry_count: int = Field(ge=0, le=5)
    api_key_configured: bool
    api_key_hint: str | None = None
    updated_at: datetime | None = None
    model_changed: bool = False
    stale_embeddings: int = Field(default=0, ge=0)


class ImageEmbeddingSettingsUpdateRequest(BaseModel):
    enabled: bool = True
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com",
        min_length=1,
        max_length=1000,
    )
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    model_name: str = Field(
        default="qwen3-vl-embedding",
        min_length=1,
        max_length=300,
    )
    dimensions: Literal[256, 512, 768, 1024, 1536, 2048, 2560] = 1024
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_retry_count: int = Field(default=2, ge=0, le=5)


class ImageIndexStatusResponse(BaseModel):
    total_images: int = Field(ge=0)
    indexed_images: int = Field(ge=0)
    pending_images: int = Field(ge=0)
    indexed_products: int = Field(ge=0)


class ImageIndexJobStartRequest(BaseModel):
    mode: Literal["INCREMENTAL", "FULL_REBUILD"] = "INCREMENTAL"
    confirm_full_rebuild: bool = False


class ImageIndexJobResponse(BaseModel):
    id: UUID
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    status: Literal["QUEUED", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED"]
    total_images: int = Field(ge=0)
    processed_images: int = Field(ge=0)
    failed_images: int = Field(ge=0)
    embeddings: int = Field(ge=0)
    remaining_images: int = Field(ge=0)
    progress_percent: float = Field(ge=0, le=100)
    current_image_id: UUID | None = None
    current_product_name: str | None = None
    error_message: str | None = None
    pause_requested: bool = False
    pause_requested_at: datetime | None = None
    paused_at: datetime | None = None
    resumable: bool = False
    checkpoint_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
