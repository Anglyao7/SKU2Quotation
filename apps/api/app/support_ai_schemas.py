from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


SupportAIMode = Literal["OFF", "DRAFT", "SHADOW", "AUTO_LIMITED", "AUTO"]
KnowledgeClassification = Literal["PUBLIC", "CUSTOMER_APPROVED"]
KnowledgeSourceStatus = Literal[
    "PROCESSING", "READY", "APPROVED", "REVOKED", "FAILED"
]
SupportAIRunStatus = Literal[
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "NEEDS_REVIEW",
    "HANDOFF",
    "FAILED",
    "CANCELLED",
    "SKIPPED",
]


class SupportAIProviderSettingsResponse(BaseModel):
    source: Literal["database", "environment", "disabled"]
    provider: str
    enabled: bool
    base_url: str | None = None
    model_name: str | None = None
    timeout_seconds: int = Field(ge=1, le=180)
    max_output_tokens: int = Field(ge=128, le=32768)
    temperature: float = Field(ge=0, le=2)
    api_key_configured: bool
    api_key_hint: str | None = None
    updated_at: datetime | None = None


class SupportAIProviderSettingsUpdate(BaseModel):
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=1000)
    model_name: str = Field(min_length=1, max_length=300)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=45, ge=1, le=180)
    max_output_tokens: int = Field(default=2048, ge=128, le=32768)
    temperature: float = Field(default=0.1, ge=0, le=2)

    @field_validator("base_url", "model_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportAISettingsResponse(BaseModel):
    mode: SupportAIMode
    sku_knowledge_enabled: bool
    file_knowledge_enabled: bool
    multilingual_enabled: bool
    min_retrieval_score: float = Field(ge=0, le=1)
    min_answer_confidence: float = Field(ge=0, le=1)
    max_sources: int = Field(ge=1, le=12)
    daily_auto_reply_limit: int = Field(ge=1, le=100000)
    system_prompt: str | None = None
    handoff_messages: dict[str, str] = Field(default_factory=dict)
    prompt_version: int = Field(ge=1)
    provider_configured: bool
    approved_file_sources: int = Field(ge=0)
    indexed_sku_products: int = Field(ge=0)
    updated_at: datetime | None = None


class SupportAISettingsUpdate(BaseModel):
    mode: SupportAIMode
    sku_knowledge_enabled: bool = True
    file_knowledge_enabled: bool = True
    multilingual_enabled: bool = True
    min_retrieval_score: float = Field(default=0.12, ge=0, le=1)
    min_answer_confidence: float = Field(default=0.65, ge=0, le=1)
    max_sources: int = Field(default=5, ge=1, le=12)
    daily_auto_reply_limit: int = Field(default=500, ge=1, le=100000)
    system_prompt: str | None = Field(default=None, max_length=12000)
    handoff_messages: dict[str, str] = Field(default_factory=dict)

    @field_validator("system_prompt", mode="before")
    @classmethod
    def normalize_prompt(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("handoff_messages")
    @classmethod
    def normalize_handoff_messages(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for locale, message in value.items():
            key = str(locale).strip()[:35]
            text = str(message).strip()
            if key and text:
                normalized[key] = text[:1000]
        return normalized


class SupportAIKnowledgeSourceResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    source_type: Literal["FILE"] = "FILE"
    classification: KnowledgeClassification
    language: str
    status: KnowledgeSourceStatus
    original_filename: str
    content_type: str | None = None
    sha256: str
    byte_size: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    version: int = Field(ge=1)
    failure_code: str | None = None
    failure_message: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SupportAIKnowledgeSourceUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    classification: KnowledgeClassification = "CUSTOMER_APPROVED"
    language: str = Field(default="und", min_length=2, max_length=35)

    @field_validator("title", "language", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None


class SupportAIIngestionJobResponse(BaseModel):
    id: UUID
    source_id: UUID
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]
    progress: int = Field(ge=0, le=100)
    parser_identifier: str | None = None
    parser_version: str | None = None
    chunks_written: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class SupportAIKnowledgeUploadResponse(BaseModel):
    source: SupportAIKnowledgeSourceResponse
    job: SupportAIIngestionJobResponse


class SupportAIEvidenceResponse(BaseModel):
    citation_number: int = Field(ge=1)
    source_type: Literal["SKU", "FILE"]
    source_entity_id: str
    source_title: str
    source_version: int = Field(ge=1)
    classification: KnowledgeClassification
    locator: dict[str, object] = Field(default_factory=dict)
    excerpt: str
    score: float = Field(ge=0, le=1)


class SupportAIRunResponse(BaseModel):
    id: UUID
    ai_task_id: UUID
    conversation_id: UUID | None = None
    input_message_id: UUID | None = None
    output_message_id: UUID | None = None
    trigger_type: Literal["CHAT", "TEST"]
    mode_snapshot: SupportAIMode
    status: SupportAIRunStatus
    question: str
    visitor_locale: str
    detected_language: str | None = None
    normalized_query: str | None = None
    answer: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    handoff_reason: str | None = None
    provider: str | None = None
    model_name: str | None = None
    prompt_version: int = Field(ge=1)
    retrieval_count: int = Field(ge=0)
    decision_trace: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    evidence: list[SupportAIEvidenceResponse] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SupportAIRunPageResponse(BaseModel):
    items: list[SupportAIRunResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=1)


class SupportAITestRunRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="zh-CN", min_length=2, max_length=35)

    @field_validator("question", "locale", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

