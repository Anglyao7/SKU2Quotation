from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..embedding_management_models import EmbeddingProviderSettingsRow
from ..model_mixins import utcnow
from .embedding import (
    EmbeddingProvider,
    EmbeddingProviderError,
    _embedding_endpoint,
    configured_text_embedding_provider,
    openai_compatible_embedding_provider,
)


SETTINGS_ID = "TEXT_EMBEDDING"


@dataclass(frozen=True)
class EmbeddingConfigurationSnapshot:
    source: str
    provider: str
    base_url: str | None
    model_name: str
    model_version: str
    dimensions: int
    timeout_seconds: int
    api_key_configured: bool
    api_key_hint: str | None
    updated_at: datetime | None


def _master_secret() -> str:
    configured_secret = os.getenv("EMBEDDING_SETTINGS_MASTER_KEY", "").strip()
    secret = configured_secret or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
    managed_environment = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    if configured_secret and managed_environment and len(configured_secret) < 32:
        raise EmbeddingProviderError(
            "embedding settings encryption key must contain at least 32 characters"
        )
    if secret:
        return secret
    if managed_environment:
        raise EmbeddingProviderError(
            "embedding settings encryption key is not configured"
        )
    return "local-development-only-embedding-settings-key"


def _fernet() -> Fernet:
    material = hashlib.sha256(
        f"atc:embedding-settings:v1:{_master_secret()}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if not normalized:
        raise EmbeddingProviderError("embedding API key is required")
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise EmbeddingProviderError(
            "stored embedding API key cannot be decrypted"
        ) from exc


def managed_model_version(*, base_url: str, model_name: str, dimensions: int) -> str:
    endpoint = _embedding_endpoint(base_url)
    identity = f"{endpoint}|{model_name.strip()}|{dimensions}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"managed-{digest}-d{dimensions}"


def get_managed_embedding_settings(
    session: Session,
) -> EmbeddingProviderSettingsRow | None:
    return session.get(EmbeddingProviderSettingsRow, SETTINGS_ID)


def resolved_text_embedding_provider(session: Session) -> EmbeddingProvider:
    settings = get_managed_embedding_settings(session)
    if settings is None or not settings.is_active:
        return configured_text_embedding_provider()
    return openai_compatible_embedding_provider(
        api_key=decrypt_api_key(settings.api_key_ciphertext),
        base_url=settings.base_url,
        model_name=settings.model_name,
        dimensions=settings.dimensions,
        model_version=settings.model_version,
        timeout_seconds=float(settings.timeout_seconds),
    )


def embedding_configuration_snapshot(
    session: Session,
) -> EmbeddingConfigurationSnapshot:
    settings = get_managed_embedding_settings(session)
    if settings is not None and settings.is_active:
        return EmbeddingConfigurationSnapshot(
            source="database",
            provider=settings.provider,
            base_url=settings.base_url,
            model_name=settings.model_name,
            model_version=settings.model_version,
            dimensions=settings.dimensions,
            timeout_seconds=settings.timeout_seconds,
            api_key_configured=bool(settings.api_key_ciphertext),
            api_key_hint=(
                f"••••{settings.api_key_last_four}"
                if settings.api_key_last_four
                else None
            ),
            updated_at=settings.updated_at,
        )

    provider = configured_text_embedding_provider()
    is_remote = provider.identity.provider == "openai-compatible"
    raw_api_key = os.getenv("TEXT_EMBEDDING_API_KEY", "").strip()
    return EmbeddingConfigurationSnapshot(
        source="environment" if is_remote else "deterministic",
        provider=provider.identity.provider,
        base_url=(
            os.getenv("TEXT_EMBEDDING_BASE_URL", "").strip() or None
            if is_remote
            else None
        ),
        model_name=provider.identity.model_name,
        model_version=provider.identity.model_version,
        dimensions=provider.identity.dimensions,
        timeout_seconds=int(
            float(os.getenv("TEXT_EMBEDDING_TIMEOUT_SECONDS", "20"))
        ),
        api_key_configured=bool(raw_api_key) if is_remote else False,
        api_key_hint=f"••••{raw_api_key[-4:]}" if is_remote and raw_api_key else None,
        updated_at=None,
    )


def save_managed_embedding_settings(
    session: Session,
    *,
    base_url: str,
    model_name: str,
    dimensions: int,
    timeout_seconds: int,
    api_key: str | None,
    updated_by_user_id: UUID,
) -> EmbeddingProviderSettingsRow:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_model = model_name.strip()
    _embedding_endpoint(normalized_base_url)
    if not normalized_model:
        raise EmbeddingProviderError("embedding model is required")

    settings = get_managed_embedding_settings(session)
    normalized_key = api_key.strip() if api_key is not None else ""
    if settings is None and not normalized_key:
        normalized_key = os.getenv("TEXT_EMBEDDING_API_KEY", "").strip()
    if settings is None and not normalized_key:
        raise EmbeddingProviderError(
            "embedding API key is required for the first configuration"
        )
    if settings is None:
        settings = EmbeddingProviderSettingsRow(
            id=SETTINGS_ID,
            provider="openai-compatible",
            base_url=normalized_base_url,
            model_name=normalized_model,
            model_version=managed_model_version(
                base_url=normalized_base_url,
                model_name=normalized_model,
                dimensions=dimensions,
            ),
            dimensions=dimensions,
            timeout_seconds=timeout_seconds,
            api_key_ciphertext=encrypt_api_key(normalized_key),
            api_key_last_four=normalized_key[-4:] or None,
            is_active=True,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(settings)
    else:
        settings.base_url = normalized_base_url
        settings.model_name = normalized_model
        settings.model_version = managed_model_version(
            base_url=normalized_base_url,
            model_name=normalized_model,
            dimensions=dimensions,
        )
        settings.dimensions = dimensions
        settings.timeout_seconds = timeout_seconds
        settings.is_active = True
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if normalized_key:
            settings.api_key_ciphertext = encrypt_api_key(normalized_key)
            settings.api_key_last_four = normalized_key[-4:]
    session.flush()
    return settings
