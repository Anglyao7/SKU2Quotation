from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ImageEnhancementTaskStatus = Literal[
    "QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"
]
ImageEnhancementItemStatus = Literal[
    "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"
]
ImageEnhancementReviewStatus = Literal["PENDING", "APPROVED", "REJECTED", "APPLIED"]
ImageEnhancementRatio = Literal["1:1", "4:3", "3:4", "16:9", "9:16"]
# Pixel dimensions are retained as accepted legacy values so tasks created by
# older clients can still be resumed and inspected after this migration.
ImageEnhancementSize = Literal[
    "1K", "2K", "4K", "1024x1024", "1024x768", "768x1024"
]


class ImageEnhancementTarget(BaseModel):
    product_id: UUID
    sku_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_skus(self) -> "ImageEnhancementTarget":
        self.sku_ids = list(dict.fromkeys(self.sku_ids))
        return self


class ImageEnhancementStartRequest(BaseModel):
    targets: list[ImageEnhancementTarget] = Field(min_length=1, max_length=500)
    prompt: str = Field(
        default=(
            "Enhance only the provided product image: make it sharper, clearer, and less noisy. "
            "The input image is the source of truth. Preserve the exact product, colors, materials, "
            "shape, proportions, existing text, markings, existing logos, background, lighting, and composition. "
            "Do not add, remove, redraw, or invent any logo, text, label, accessory, decoration, prop, or other object. "
            "Do not change the background or create a new design."
        ),
        min_length=1,
        max_length=2000,
    )
    ratio: ImageEnhancementRatio = "1:1"
    size: ImageEnhancementSize = "1K"

    @model_validator(mode="after")
    def unique_products(self) -> "ImageEnhancementStartRequest":
        seen: set[UUID] = set()
        normalized: list[ImageEnhancementTarget] = []
        for target in self.targets:
            if target.product_id not in seen:
                seen.add(target.product_id)
                normalized.append(target)
                continue
            existing = next(
                item for item in normalized if item.product_id == target.product_id
            )
            existing.sku_ids = list(dict.fromkeys(existing.sku_ids + target.sku_ids))
        self.targets = normalized
        self.prompt = self.prompt.strip()
        return self


class ImageEnhancementItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    sku_ids: list[UUID]
    sku_snapshot: list[dict[str, object]]
    source_image_url: str
    status: ImageEnhancementItemStatus
    review_status: ImageEnhancementReviewStatus
    result_url: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    reviewed_at: datetime | None
    applied_at: datetime | None


class ImageEnhancementTaskResponse(BaseModel):
    id: UUID
    status: ImageEnhancementTaskStatus
    prompt: str
    ratio: ImageEnhancementRatio
    size: str
    output_format: Literal["url"]
    total_items: int = Field(ge=0)
    completed_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)
    cancelled_items: int = Field(ge=0)
    progress_percent: float = Field(ge=0, le=100)
    cancellation_requested: bool
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    items: list[ImageEnhancementItemResponse]


class ImageEnhancementCancelRequest(BaseModel):
    item_ids: list[UUID] = Field(default_factory=list, max_length=500)


class ImageEnhancementReviewRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=500)
    decision: Literal["APPROVE", "REJECT"]


class ImageEnhancementConfirmRequest(BaseModel):
    item_ids: list[UUID] = Field(default_factory=list, max_length=500)
