from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeProjectionResponse(BaseModel):
    document_id: UUID
    product_id: UUID
    source_version: int
    chunks: int
    embeddings: int
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int
    idempotent: bool


class KnowledgeIndexStatusResponse(BaseModel):
    total_products: int = Field(ge=0)
    indexed_products: int = Field(ge=0)
    pending_products: int = Field(ge=0)
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int = Field(ge=1)


class KnowledgeIndexUpdateResponse(KnowledgeIndexStatusResponse):
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    processed_products: int = Field(ge=0)
    embeddings: int = Field(ge=0)


class KnowledgeIndexRebuildRequest(BaseModel):
    confirm_full_rebuild: Literal[True]


class HybridSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class SearchScoreBreakdown(BaseModel):
    keyword: float = Field(ge=0, le=1)
    semantic: float = Field(ge=0, le=1)
    attribute: float = Field(ge=0, le=1)
    tag: float = Field(ge=0, le=1)
    supplier: float = Field(ge=0, le=1)


class SearchEvidence(BaseModel):
    document_id: UUID
    chunk_id: UUID
    chunk_type: str
    content_hash: str
    excerpt: str


class HybridSearchResult(BaseModel):
    product_id: UUID
    product_code: str | None
    name: str
    source_version: int
    score: float
    score_breakdown: SearchScoreBreakdown
    supplier_signal_status: str
    evidence: list[SearchEvidence]
    ranking_version: str
    degraded_channels: list[str]


class EmbeddingModelInfo(BaseModel):
    provider: str
    name: str
    version: str
    dimensions: int


class HybridSearchResponse(BaseModel):
    query: str
    ranking_version: str
    model: EmbeddingModelInfo
    degraded_channels: list[str]
    results: list[HybridSearchResult]
