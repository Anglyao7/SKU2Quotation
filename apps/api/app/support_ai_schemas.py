from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, field_validator


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
    id: str | None = None
    configuration_name: str | None = None
    display_model_name: str | None = None
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
    configuration_name: str | None = Field(default=None, max_length=160)
    display_model_name: str | None = Field(default=None, max_length=160)
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=1000)
    model_name: str = Field(min_length=1, max_length=300)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=45, ge=1, le=180)
    max_output_tokens: int = Field(default=2048, ge=128, le=32768)
    temperature: float = Field(default=0.1, ge=0, le=2)

    @field_validator(
        "configuration_name",
        "display_model_name",
        "base_url",
        "model_name",
        mode="before",
    )
    @classmethod
    def normalize_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportAIProviderProfileWrite(BaseModel):
    configuration_name: str = Field(min_length=1, max_length=160)
    display_model_name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=1000)
    model_name: str = Field(min_length=1, max_length=300)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=45, ge=1, le=180)
    max_output_tokens: int = Field(default=2048, ge=128, le=32768)
    temperature: float = Field(default=0.1, ge=0, le=2)

    @field_validator(
        "configuration_name",
        "display_model_name",
        "base_url",
        "model_name",
        mode="before",
    )
    @classmethod
    def normalize_profile_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportAIProviderProfileCopy(BaseModel):
    configuration_name: str = Field(min_length=1, max_length=160)

    @field_validator("configuration_name", mode="before")
    @classmethod
    def normalize_copy_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SupportAIStoreConfigurationResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str
    organization_id: UUID
    enabled: bool
    provider_profile_id: str | None = None
    model_display_name: str | None = None
    updated_at: datetime | None = None


class SupportAIStoreProviderBindingUpdate(BaseModel):
    provider_profile_id: str | None = Field(default=None, max_length=40)


class SupportAIStoreProviderBulkBinding(BaseModel):
    tenant_ids: list[UUID] = Field(min_length=1, max_length=500)
    provider_profile_id: str | None = Field(default=None, max_length=40)


class SupportAIStoreConfigurationCopy(BaseModel):
    source_tenant_id: UUID
    target_tenant_ids: list[UUID] = Field(min_length=1, max_length=500)
    copy_model_binding: bool = True
    copy_policy: bool = True
    copy_enabled_state: bool = False

    @field_validator("target_tenant_ids")
    @classmethod
    def unique_targets(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class SupportAIAgentStoreResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str


class SupportAIAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    provider_profile_id: str | None = Field(default=None, max_length=40)
    tenant_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("tenant_ids")
    @classmethod
    def unique_tenants(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class SupportAIAgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    enabled: bool | None = None
    provider_profile_id: str | None = Field(default=None, max_length=40)
    tenant_ids: list[UUID] | None = Field(default=None, max_length=500)
    sku_knowledge_enabled: bool | None = None
    file_knowledge_enabled: bool | None = None
    multilingual_enabled: bool | None = None
    min_retrieval_score: float | None = Field(default=None, ge=0, le=1)
    min_answer_confidence: float | None = Field(default=None, ge=0, le=1)
    max_sources: int | None = Field(default=None, ge=1, le=12)
    daily_auto_reply_limit: int | None = Field(default=None, ge=1, le=100000)
    public_company_introduction: str | None = Field(default=None, max_length=2000)
    public_service_scope: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = Field(default=None, max_length=12000)
    handoff_messages: dict[str, str] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_optional_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "description",
        "public_company_introduction",
        "public_service_scope",
        "system_prompt",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("tenant_ids")
    @classmethod
    def unique_optional_tenants(cls, value: list[UUID] | None) -> list[UUID] | None:
        return list(dict.fromkeys(value)) if value is not None else None

    @field_validator("handoff_messages")
    @classmethod
    def normalize_agent_handoff_messages(
        cls, value: dict[str, str] | None
    ) -> dict[str, str] | None:
        if value is None:
            return None
        normalized: dict[str, str] = {}
        for locale, message in value.items():
            key = str(locale).strip()[:35]
            text = str(message).strip()
            if key and text:
                normalized[key] = text[:1000]
        return normalized


class SupportAIAgentResponse(BaseModel):
    id: UUID
    agent_code: str = Field(pattern=r"^\d{8}$")
    name: str
    description: str | None = None
    enabled: bool
    provider_profile_id: str | None = None
    model_display_name: str | None = None
    api_configured: bool
    sku_knowledge_enabled: bool
    file_knowledge_enabled: bool
    multilingual_enabled: bool
    min_retrieval_score: float = Field(ge=0, le=1)
    min_answer_confidence: float = Field(ge=0, le=1)
    max_sources: int = Field(ge=1, le=12)
    daily_auto_reply_limit: int = Field(ge=1, le=100000)
    public_company_introduction: str | None = None
    public_service_scope: str | None = None
    system_prompt: str | None = None
    handoff_messages: dict[str, str] = Field(default_factory=dict)
    stores: list[SupportAIAgentStoreResponse] = Field(default_factory=list)
    knowledge_source_count: int = Field(ge=0)
    approved_knowledge_source_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


TrainingCaseStatus = Literal["DRAFT", "APPROVED", "ARCHIVED"]
TrainingResponseAction = Literal["ANSWER", "CLARIFY", "HANDOFF"]
TrainingGroundingMode = Literal[
    "EVIDENCE", "GENERAL_GUIDANCE", "APPROVED_COMPANY_PROFILE"
]
TrainingSourceType = Literal[
    "MANUAL", "PRODUCT_GENERATED", "CONVERSATION_CORRECTION", "IMPORT"
]


class SupportAITrainingCaseWrite(BaseModel):
    external_id: str | None = Field(default=None, max_length=120)
    source_tenant_id: UUID | None = None
    title: str = Field(min_length=1, max_length=240)
    language: str = Field(default="zh-CN", min_length=2, max_length=35)
    customer_message: str = Field(min_length=1, max_length=4000)
    ideal_response: str = Field(min_length=1, max_length=12000)
    response_action: TrainingResponseAction = "ANSWER"
    grounding_mode: TrainingGroundingMode = "EVIDENCE"
    behavior_notes: str | None = Field(default=None, max_length=6000)
    required_evidence_types: list[Literal["SKU", "FILE", "COMPANY_PROFILE"]] = Field(
        default_factory=list,
        max_length=3,
    )
    tags: list[str] = Field(default_factory=list, max_length=20)
    forbidden_patterns: list[str] = Field(default_factory=list, max_length=20)
    source_type: TrainingSourceType = "MANUAL"
    status: TrainingCaseStatus = "DRAFT"
    sort_order: int = Field(default=0, ge=0, le=100000)

    @field_validator(
        "external_id",
        "title",
        "language",
        "customer_message",
        "ideal_response",
        "behavior_notes",
        mode="before",
    )
    @classmethod
    def normalize_training_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("required_evidence_types", "tags", "forbidden_patterns")
    @classmethod
    def unique_training_lists(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip()[:240] for item in value if item.strip()))


class SupportAITrainingCaseResponse(BaseModel):
    id: UUID
    agent_id: UUID
    external_id: str
    source_tenant_id: UUID | None = None
    title: str
    language: str
    customer_message: str
    ideal_response: str
    response_action: TrainingResponseAction
    grounding_mode: TrainingGroundingMode
    behavior_notes: str | None = None
    required_evidence_types: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    source_type: TrainingSourceType
    status: TrainingCaseStatus
    sort_order: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class SupportAITrainingRuleWrite(BaseModel):
    rule_key: str | None = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    instruction: str = Field(min_length=1, max_length=6000)
    scopes: list[str] = Field(default_factory=list, max_length=20)
    source_case_ids: list[UUID] = Field(default_factory=list, max_length=200)
    priority: int = Field(default=100, ge=0, le=1000)
    status: TrainingCaseStatus = "DRAFT"

    @field_validator("rule_key", "title", "instruction", mode="before")
    @classmethod
    def normalize_rule_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip()[:80] for item in value if item.strip()))


class SupportAITrainingRuleResponse(BaseModel):
    id: UUID
    agent_id: UUID
    rule_key: str
    title: str
    instruction: str
    scopes: list[str] = Field(default_factory=list)
    source_case_ids: list[UUID] = Field(default_factory=list)
    priority: int = Field(ge=0, le=1000)
    status: TrainingCaseStatus
    created_at: datetime
    updated_at: datetime


class SupportAITrainingVersionResponse(BaseModel):
    id: UUID
    agent_id: UUID
    version_number: int = Field(ge=1)
    status: Literal["PUBLISHED", "RETIRED"]
    package_hash: str = Field(min_length=64, max_length=64)
    compiled_prompt: str
    case_count: int = Field(ge=0)
    rule_count: int = Field(ge=0)
    release_notes: str | None = None
    published_at: datetime
    activated_at: datetime
    retired_at: datetime | None = None


class SupportAITrainingOverviewResponse(BaseModel):
    agent_id: UUID
    cases: list[SupportAITrainingCaseResponse] = Field(default_factory=list)
    rules: list[SupportAITrainingRuleResponse] = Field(default_factory=list)
    versions: list[SupportAITrainingVersionResponse] = Field(default_factory=list)
    active_version_id: UUID | None = None
    active_version_number: int | None = None
    draft_case_count: int = Field(ge=0)
    approved_case_count: int = Field(ge=0)
    draft_rule_count: int = Field(ge=0)
    approved_rule_count: int = Field(ge=0)


class SupportAITrainingPreviewResponse(BaseModel):
    compiled_prompt: str
    package_hash: str = Field(min_length=64, max_length=64)
    approved_case_count: int = Field(ge=0)
    approved_rule_count: int = Field(ge=0)


class SupportAITrainingPublishRequest(BaseModel):
    release_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("release_notes", mode="before")
    @classmethod
    def normalize_release_notes(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None


class SupportAITrainingCopyRequest(BaseModel):
    target_agent_id: UUID
    include_cases: bool = True
    include_rules: bool = True


class SupportAITrainingPackage(BaseModel):
    schema_version: Literal["support-ai-training/v1"] = "support-ai-training/v1"
    agent: dict[str, Any] = Field(default_factory=dict)
    boundary: list[str] = Field(default_factory=list)
    rules: list[SupportAITrainingRuleWrite] = Field(default_factory=list, max_length=500)
    cases: list[SupportAITrainingCaseWrite] = Field(default_factory=list, max_length=2000)


class SupportAISettingsResponse(BaseModel):
    enabled: bool
    sku_knowledge_enabled: bool
    file_knowledge_enabled: bool
    multilingual_enabled: bool
    min_retrieval_score: float = Field(ge=0, le=1)
    min_answer_confidence: float = Field(ge=0, le=1)
    max_sources: int = Field(ge=1, le=12)
    daily_auto_reply_limit: int = Field(ge=1, le=100000)
    public_company_introduction: str | None = None
    public_service_scope: str | None = None
    system_prompt: str | None = None
    handoff_messages: dict[str, str] = Field(default_factory=dict)
    prompt_version: int = Field(ge=1)
    model_display_name: str | None = None
    approved_file_sources: int = Field(ge=0)
    indexed_sku_products: int = Field(ge=0)
    updated_at: datetime | None = None


class SupportAISettingsUpdate(BaseModel):
    enabled: bool
    sku_knowledge_enabled: bool = True
    file_knowledge_enabled: bool = True
    multilingual_enabled: bool = True
    min_retrieval_score: float = Field(default=0.12, ge=0, le=1)
    min_answer_confidence: float = Field(default=0.65, ge=0, le=1)
    max_sources: int = Field(default=5, ge=1, le=12)
    daily_auto_reply_limit: int = Field(default=500, ge=1, le=100000)
    public_company_introduction: str | None = Field(default=None, max_length=2000)
    public_service_scope: str | None = Field(default=None, max_length=2000)
    system_prompt: str | None = Field(default=None, max_length=12000)
    handoff_messages: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "public_company_introduction",
        "public_service_scope",
        "system_prompt",
        mode="before",
    )
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


class SupportAIAgentKnowledgeSourceResponse(BaseModel):
    tenant_id: UUID
    tenant_name: str
    source: SupportAIKnowledgeSourceResponse


class SupportAIAgentKnowledgeUploadItem(BaseModel):
    tenant_id: UUID
    tenant_name: str
    source: SupportAIKnowledgeSourceResponse
    job: SupportAIIngestionJobResponse


class SupportAIAgentKnowledgeUploadResponse(BaseModel):
    items: list[SupportAIAgentKnowledgeUploadItem]


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
    enabled_snapshot: bool
    status: SupportAIRunStatus
    question: str
    visitor_locale: str
    detected_language: str | None = None
    normalized_query: str | None = None
    answer: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    handoff_reason: str | None = None
    model_display_name: str | None = None
    prompt_version: int = Field(ge=1)
    training_version_id: UUID | None = None
    training_case_ids: list[UUID] = Field(default_factory=list)
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
