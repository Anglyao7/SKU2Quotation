from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from .translation_constants import MAX_TRANSLATION_TIMEOUT_SECONDS


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
TranslationProviderKind = Literal[
    "openai-compatible",
    "deeplx",
    "aliyun-alimt",
]
CatalogTranslationExecutionMode = Literal["REALTIME", "QWEN_BATCH"]


class TranslationSettingsResponse(BaseModel):
    source: Literal["database", "environment", "disabled"]
    provider: str
    enabled: bool
    base_url: str | None = None
    model_name: str | None = None
    region_id: str | None = None
    timeout_seconds: int = Field(
        ge=1,
        le=MAX_TRANSLATION_TIMEOUT_SECONDS,
    )
    max_tokens: int = Field(ge=512, le=32768)
    requests_per_minute: int = Field(ge=1, le=10_000)
    max_retry_count: int = Field(ge=0, le=10)
    catalog_batch_size: int = Field(ge=1, le=200)
    catalog_batch_characters: int = Field(ge=1_000, le=100_000)
    catalog_concurrency: int = Field(ge=1, le=10)
    catalog_execution_mode: CatalogTranslationExecutionMode
    reasoning_effort: ReasoningEffort
    api_key_configured: bool
    api_key_hint: str | None = None
    access_key_id_configured: bool = False
    access_key_id_hint: str | None = None
    batch_base_url: str
    batch_model_name: str
    batch_api_key_configured: bool = False
    batch_api_key_hint: str | None = None
    updated_at: datetime | None = None


class TranslationProviderParameters(BaseModel):
    provider: TranslationProviderKind = "openai-compatible"
    base_url: str = Field(default="", max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    access_key_id: SecretStr | None = Field(default=None, max_length=4096)
    model_name: str = Field(min_length=1, max_length=300)
    region_id: str | None = Field(default=None, max_length=100)
    timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=MAX_TRANSLATION_TIMEOUT_SECONDS,
    )
    max_tokens: int = Field(default=16384, ge=512, le=32768)
    requests_per_minute: int = Field(default=60, ge=1, le=10_000)
    max_retry_count: int = Field(default=3, ge=0, le=10)
    catalog_batch_size: int = Field(default=50, ge=1, le=200)
    catalog_batch_characters: int = Field(
        default=10_000,
        ge=1_000,
        le=100_000,
    )
    catalog_concurrency: int = Field(default=3, ge=1, le=10)
    catalog_execution_mode: CatalogTranslationExecutionMode = "REALTIME"
    batch_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        max_length=1000,
    )
    batch_model_name: str = Field(
        default="qwen3.7-flash-2026-07-15",
        min_length=1,
        max_length=300,
    )
    batch_api_key: SecretStr | None = Field(default=None, max_length=4096)
    reasoning_effort: ReasoningEffort = "low"


class TranslationSettingsUpdateRequest(TranslationProviderParameters):
    enabled: bool = True


class TranslationSettingsTestRequest(TranslationProviderParameters):
    pass


class TranslationSettingsTestResponse(BaseModel):
    success: Literal[True] = True
    provider: str
    model_name: str
    latency_ms: int = Field(ge=0)
    translated_text: str
