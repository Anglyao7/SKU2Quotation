from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


DEFAULT_AI_SEARCH_RECOMMENDED_QUESTIONS = [
    "适合巴西市场的小型防水狗玩具有哪些？",
    "请推荐一款适合户外使用、容易收纳的商品。",
    "有哪些商品支持定制，并且 MOQ 比较友好？",
]


class KnowledgeProjectionResponse(BaseModel):
    product_id: UUID
    source_version: int
    chunks: int
    embeddings: int
    idempotent: bool


class KnowledgeIndexStatusResponse(BaseModel):
    total_products: int = Field(ge=0)
    indexed_products: int = Field(ge=0)
    pending_products: int = Field(ge=0)


class KnowledgeIndexUpdateResponse(KnowledgeIndexStatusResponse):
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    processed_products: int = Field(ge=0)
    embeddings: int = Field(ge=0)


class KnowledgeIndexRebuildRequest(BaseModel):
    confirm_full_rebuild: Literal[True]


class KnowledgeIndexJobStartRequest(BaseModel):
    mode: Literal["INCREMENTAL", "FULL_REBUILD"] = "INCREMENTAL"
    confirm_full_rebuild: bool = False


class KnowledgeIndexJobResponse(BaseModel):
    id: UUID
    mode: Literal["INCREMENTAL", "FULL_REBUILD"]
    status: Literal["QUEUED", "RUNNING", "PAUSED", "SUCCEEDED", "FAILED"]
    total_products: int = Field(ge=0)
    processed_products: int = Field(ge=0)
    failed_products: int = Field(ge=0)
    embeddings: int = Field(ge=0)
    remaining_products: int = Field(ge=0)
    progress_percent: float = Field(ge=0, le=100)
    current_product_id: UUID | None = None
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


class EmbeddingSettingsResponse(BaseModel):
    source: Literal["database", "environment", "deterministic"]
    provider: str
    base_url: str | None = None
    model_name: str
    model_version: str
    dimensions: int = Field(ge=1, le=2000)
    timeout_seconds: int = Field(ge=1, le=120)
    max_retry_count: int = Field(ge=0, le=10)
    api_key_configured: bool
    api_key_hint: str | None = None
    updated_at: datetime | None = None
    model_changed: bool = False
    cleared_product_embeddings: int = Field(default=0, ge=0)
    cleared_file_embeddings: int = Field(default=0, ge=0)
    invalidated_products: int = Field(default=0, ge=0)


class EmbeddingSettingsUpdateRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    model_name: str = Field(min_length=1, max_length=300)
    dimensions: int = Field(default=1024, ge=1, le=2000)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_retry_count: int = Field(default=3, ge=0, le=10)


class HybridSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class AISearchRecommendedQuestionsResponse(BaseModel):
    questions: list[str] = Field(min_length=3, max_length=3)


class AISearchRecommendedQuestionsUpdate(BaseModel):
    questions: list[str] = Field(min_length=3, max_length=3)

    @field_validator("questions")
    @classmethod
    def normalize_questions(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            question = str(item).strip()[:200]
            key = question.casefold()
            if not question:
                raise ValueError("推荐问题不能为空")
            if key in seen:
                raise ValueError("推荐问题不能重复")
            seen.add(key)
            normalized.append(question)
        return normalized


class SearchScoreBreakdown(BaseModel):
    keyword: float = Field(ge=0, le=1)
    semantic: float = Field(ge=0, le=1)
    attribute: float = Field(ge=0, le=1)
    tag: float = Field(ge=0, le=1)
    supplier: float = Field(ge=0, le=1)


class SearchEvidence(BaseModel):
    chunk_type: str
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


class HybridSearchResponse(BaseModel):
    query: str
    degraded: bool = False
    results: list[HybridSearchResult]
