from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ImageProjectionResponse(BaseModel):
    observation_id: UUID
    embedding_id: UUID
    product_id: UUID
    product_image_id: UUID
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int
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
    evidence: dict[str, object]
    conflicts: list[str]


class ImageSearchResponse(BaseModel):
    id: UUID
    status: Literal["COMPLETED", "NO_RELIABLE_MATCH"]
    model_provider: str
    model_name: str
    model_version: str
    ranking_version: str
    expires_at: datetime
    warnings: list[str]
    results: list[ImageSearchResult]
