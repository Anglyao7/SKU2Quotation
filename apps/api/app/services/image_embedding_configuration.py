from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from ..adapters.image_intelligence import (
    QWEN3_VL_DIMENSIONS,
    QWEN_IMAGE_PREPROCESSING_VERSION,
    ImageIntelligenceProviderError,
    ImageIntelligenceUnavailable,
    dashscope_multimodal_endpoint,
    get_image_intelligence_provider,
    normalize_dashscope_multimodal_base_url,
    qwen_vl_image_embedding_provider,
)
from ..embedding_management_models import ImageEmbeddingProviderSettingsRow
from ..model_mixins import utcnow
from ..ports.image_intelligence import ImageIntelligenceProvider
from .embedding_configuration import decrypt_api_key, encrypt_api_key


SETTINGS_ID = "IMAGE_EMBEDDING"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
DEFAULT_MODEL_NAME = "qwen3-vl-embedding"
DEFAULT_DIMENSIONS = 1024


@dataclass(frozen=True, slots=True)
class ImageEmbeddingConfigurationSnapshot:
    source: str
    provider: str
    enabled: bool
    base_url: str | None
    model_name: str
    model_version: str
    dimensions: int
    timeout_seconds: int
    max_retry_count: int
    api_key_configured: bool
    api_key_hint: str | None
    updated_at: datetime | None


def managed_image_model_version(
    *,
    base_url: str,
    model_name: str,
    dimensions: int,
) -> str:
    endpoint = dashscope_multimodal_endpoint(base_url)
    identity = (
        f"{endpoint}|{model_name.strip()}|{dimensions}|"
        f"{QWEN_IMAGE_PREPROCESSING_VERSION}"
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"managed-{digest}-d{dimensions}-{QWEN_IMAGE_PREPROCESSING_VERSION}"


def get_managed_image_embedding_settings(
    session: Session,
) -> ImageEmbeddingProviderSettingsRow | None:
    return session.get(ImageEmbeddingProviderSettingsRow, SETTINGS_ID)


def _environment_provider() -> ImageIntelligenceProvider:
    profile = os.getenv("IMAGE_EMBEDDING_PROFILE", "").strip().casefold()
    if profile in {"dashscope", "qwen", "qwen3-vl-embedding"}:
        try:
            dimensions = int(
                os.getenv("IMAGE_EMBEDDING_DIMENSIONS", str(DEFAULT_DIMENSIONS))
            )
            timeout_seconds = float(
                os.getenv("IMAGE_EMBEDDING_TIMEOUT_SECONDS", "30")
            )
            max_retry_count = int(
                os.getenv("IMAGE_EMBEDDING_PROVIDER_RETRIES", "2")
            )
        except ValueError as exc:
            raise ImageIntelligenceProviderError(
                "图片 Embedding 环境配置无效"
            ) from exc
        base_url = os.getenv("IMAGE_EMBEDDING_BASE_URL", DEFAULT_BASE_URL)
        model_name = os.getenv("IMAGE_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        model_version = os.getenv("IMAGE_EMBEDDING_MODEL_VERSION", "").strip()
        return qwen_vl_image_embedding_provider(
            api_key=os.getenv("IMAGE_EMBEDDING_API_KEY", ""),
            base_url=base_url,
            model_name=model_name,
            model_version=model_version
            or managed_image_model_version(
                base_url=base_url,
                model_name=model_name,
                dimensions=dimensions,
            ),
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
            max_retry_count=max_retry_count,
        )
    return get_image_intelligence_provider()


def resolved_image_embedding_provider(
    session: Session,
) -> ImageIntelligenceProvider:
    settings = get_managed_image_embedding_settings(session)
    if settings is None:
        return _environment_provider()
    if not settings.is_active:
        raise ImageIntelligenceProviderError("图片搜索模型已关闭")
    effective_model_version = managed_image_model_version(
        base_url=settings.base_url,
        model_name=settings.model_name,
        dimensions=settings.dimensions,
    )
    return qwen_vl_image_embedding_provider(
        api_key=decrypt_api_key(settings.api_key_ciphertext),
        base_url=settings.base_url,
        model_name=settings.model_name,
        model_version=effective_model_version,
        dimensions=settings.dimensions,
        timeout_seconds=float(settings.timeout_seconds),
        max_retry_count=settings.max_retry_count,
    )


def image_embedding_configuration_snapshot(
    session: Session,
) -> ImageEmbeddingConfigurationSnapshot:
    settings = get_managed_image_embedding_settings(session)
    if settings is not None:
        normalized_base_url = normalize_dashscope_multimodal_base_url(
            settings.base_url
        )
        effective_model_version = managed_image_model_version(
            base_url=normalized_base_url,
            model_name=settings.model_name,
            dimensions=settings.dimensions,
        )
        return ImageEmbeddingConfigurationSnapshot(
            source="database",
            provider=settings.provider,
            enabled=bool(settings.is_active),
            base_url=normalized_base_url,
            model_name=settings.model_name,
            model_version=effective_model_version,
            dimensions=settings.dimensions,
            timeout_seconds=settings.timeout_seconds,
            max_retry_count=settings.max_retry_count,
            api_key_configured=bool(settings.api_key_ciphertext),
            api_key_hint=(
                f"••••{settings.api_key_last_four}"
                if settings.api_key_last_four
                else None
            ),
            updated_at=settings.updated_at,
        )

    profile = os.getenv("IMAGE_EMBEDDING_PROFILE", "").strip().casefold()
    if profile in {"dashscope", "qwen", "qwen3-vl-embedding"}:
        provider = _environment_provider()
        raw_key = os.getenv("IMAGE_EMBEDDING_API_KEY", "").strip()
        return ImageEmbeddingConfigurationSnapshot(
            source="environment",
            provider=provider.identity.provider,
            enabled=True,
            base_url=os.getenv("IMAGE_EMBEDDING_BASE_URL", DEFAULT_BASE_URL),
            model_name=provider.identity.model_name,
            model_version=provider.identity.model_version,
            dimensions=provider.identity.dimensions,
            timeout_seconds=int(
                float(os.getenv("IMAGE_EMBEDDING_TIMEOUT_SECONDS", "30"))
            ),
            max_retry_count=int(
                os.getenv("IMAGE_EMBEDDING_PROVIDER_RETRIES", "2")
            ),
            api_key_configured=bool(raw_key),
            api_key_hint=f"••••{raw_key[-4:]}" if raw_key else None,
            updated_at=None,
        )

    try:
        provider = get_image_intelligence_provider()
    except ImageIntelligenceUnavailable:
        return ImageEmbeddingConfigurationSnapshot(
            source="unconfigured",
            provider="dashscope",
            enabled=False,
            base_url=DEFAULT_BASE_URL,
            model_name=DEFAULT_MODEL_NAME,
            model_version=managed_image_model_version(
                base_url=DEFAULT_BASE_URL,
                model_name=DEFAULT_MODEL_NAME,
                dimensions=DEFAULT_DIMENSIONS,
            ),
            dimensions=DEFAULT_DIMENSIONS,
            timeout_seconds=30,
            max_retry_count=2,
            api_key_configured=False,
            api_key_hint=None,
            updated_at=None,
        )
    return ImageEmbeddingConfigurationSnapshot(
        source="deterministic",
        provider=provider.identity.provider,
        enabled=True,
        base_url=None,
        model_name=provider.identity.model_name,
        model_version=provider.identity.model_version,
        dimensions=provider.identity.dimensions,
        timeout_seconds=30,
        max_retry_count=0,
        api_key_configured=False,
        api_key_hint=None,
        updated_at=None,
    )


def save_managed_image_embedding_settings(
    session: Session,
    *,
    enabled: bool,
    base_url: str,
    model_name: str,
    dimensions: int,
    timeout_seconds: int,
    max_retry_count: int,
    api_key: str | None,
    updated_by_user_id: UUID,
) -> ImageEmbeddingProviderSettingsRow:
    normalized_base_url = normalize_dashscope_multimodal_base_url(base_url)
    normalized_model = model_name.strip()
    dashscope_multimodal_endpoint(normalized_base_url)
    if not normalized_model:
        raise ImageIntelligenceProviderError("图片 Embedding 模型名称不能为空")
    if dimensions not in QWEN3_VL_DIMENSIONS:
        raise ImageIntelligenceProviderError("Qwen3-VL 不支持该向量维度")
    if timeout_seconds < 1 or timeout_seconds > 120:
        raise ImageIntelligenceProviderError("请求超时必须在 1–120 秒之间")
    if max_retry_count < 0 or max_retry_count > 5:
        raise ImageIntelligenceProviderError("重试次数必须在 0–5 之间")

    settings = get_managed_image_embedding_settings(session)
    normalized_key = api_key.strip() if api_key is not None else ""
    if settings is None and not normalized_key:
        normalized_key = os.getenv("IMAGE_EMBEDDING_API_KEY", "").strip()
    if settings is None and not normalized_key:
        raise ImageIntelligenceProviderError(
            "首次配置图片 Embedding 时必须填写 API Key"
        )
    model_version = managed_image_model_version(
        base_url=normalized_base_url,
        model_name=normalized_model,
        dimensions=dimensions,
    )
    if settings is None:
        settings = ImageEmbeddingProviderSettingsRow(
            id=SETTINGS_ID,
            provider="dashscope",
            base_url=normalized_base_url,
            model_name=normalized_model,
            model_version=model_version,
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
            max_retry_count=max_retry_count,
            api_key_ciphertext=encrypt_api_key(normalized_key),
            api_key_last_four=normalized_key[-4:] or None,
            is_active=enabled,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(settings)
    else:
        settings.base_url = normalized_base_url
        settings.model_name = normalized_model
        settings.model_version = model_version
        settings.dimensions = dimensions
        settings.timeout_seconds = timeout_seconds
        settings.max_retry_count = max_retry_count
        settings.is_active = enabled
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if normalized_key:
            settings.api_key_ciphertext = encrypt_api_key(normalized_key)
            settings.api_key_last_four = normalized_key[-4:]
    session.flush()
    return settings
