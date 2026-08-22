from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


ImageGenerationOutputFormat = Literal["url", "b64_json"]


class ImageGenerationSettingsResponse(BaseModel):
    source: Literal["database", "environment", "disabled"]
    provider: str
    enabled: bool
    base_url: str | None = None
    model_name: str | None = None
    system_prompt: str
    timeout_seconds: int = Field(ge=60, le=360)
    requests_per_minute: int = Field(default=6, ge=1, le=10_000)
    concurrency_limit: int = Field(default=3, ge=1, le=32)
    api_key_configured: bool
    api_key_hint: str | None = None
    supported_workflows: list[Literal["image-to-image"]] = Field(
        default_factory=lambda: ["image-to-image"]
    )
    supported_output_formats: list[ImageGenerationOutputFormat] = Field(
        default_factory=lambda: ["url", "b64_json"]
    )
    updated_at: datetime | None = None


class ImageGenerationSettingsUpdateRequest(BaseModel):
    enabled: bool = True
    base_url: str = Field(min_length=1, max_length=1000)
    model_name: str = Field(min_length=1, max_length=300)
    system_prompt: str | None = Field(default=None, max_length=12000)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    timeout_seconds: int = Field(default=180, ge=60, le=360)
    requests_per_minute: int = Field(default=6, ge=1, le=10_000)
    concurrency_limit: int = Field(default=3, ge=1, le=32)
