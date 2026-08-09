from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high"]
TranslationProviderKind = Literal["openai-compatible", "aliyun-alimt"]


class TranslationSettingsResponse(BaseModel):
    source: Literal["database", "environment", "disabled"]
    provider: str
    enabled: bool
    base_url: str | None = None
    model_name: str | None = None
    region_id: str | None = None
    timeout_seconds: int = Field(ge=1, le=120)
    max_tokens: int = Field(ge=512, le=32768)
    requests_per_minute: int = Field(ge=1, le=10_000)
    max_retry_count: int = Field(ge=0, le=10)
    catalog_batch_size: int = Field(ge=1, le=200)
    catalog_batch_characters: int = Field(ge=1_000, le=100_000)
    reasoning_effort: ReasoningEffort
    api_key_configured: bool
    api_key_hint: str | None = None
    access_key_id_configured: bool = False
    access_key_id_hint: str | None = None
    updated_at: datetime | None = None


class TranslationProviderParameters(BaseModel):
    provider: TranslationProviderKind = "openai-compatible"
    base_url: str = Field(min_length=1, max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    access_key_id: SecretStr | None = Field(default=None, max_length=4096)
    model_name: str = Field(min_length=1, max_length=300)
    region_id: str | None = Field(default=None, max_length=100)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_tokens: int = Field(default=16384, ge=512, le=32768)
    requests_per_minute: int = Field(default=60, ge=1, le=10_000)
    max_retry_count: int = Field(default=3, ge=0, le=10)
    catalog_batch_size: int = Field(default=50, ge=1, le=200)
    catalog_batch_characters: int = Field(
        default=10_000,
        ge=1_000,
        le=100_000,
    )
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
