from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..model_mixins import utcnow
from ..support_ai_models import SupportAIProviderSettingsRow
from .chat_generation import (
    ChatGenerationError,
    ChatGenerationProvider,
    chat_completions_endpoint,
    openai_compatible_chat_provider,
)


SETTINGS_ID = "SUPPORT_AI_GENERATION"


@dataclass(frozen=True, slots=True)
class SupportAIProviderSnapshot:
    source: str
    provider: str
    enabled: bool
    base_url: str | None
    model_name: str | None
    timeout_seconds: int
    max_output_tokens: int
    temperature: float
    api_key_configured: bool
    api_key_hint: str | None
    updated_at: datetime | None


def support_ai_inline_processing_enabled() -> bool:
    """Use request-local background work in development, durable workers in prod."""

    configured = os.getenv("SUPPORT_AI_WORKER_INLINE", "").strip().lower()
    if configured:
        return configured in {"1", "true", "yes"}
    return os.getenv("APP_ENV", "development").strip().lower() not in {
        "production",
        "staging",
    }


def _master_secret() -> str:
    configured = os.getenv("SUPPORT_AI_SETTINGS_MASTER_KEY", "").strip()
    secret = configured or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
    managed = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    if configured and managed and len(configured) < 32:
        raise ChatGenerationError(
            "support AI settings encryption key must contain at least 32 characters"
        )
    if secret:
        return secret
    if managed:
        raise ChatGenerationError(
            "support AI settings encryption key is not configured"
        )
    return "local-development-only-support-ai-settings-key"


def _fernet() -> Fernet:
    material = hashlib.sha256(
        f"atc:support-ai-settings:v1:{_master_secret()}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if not normalized:
        raise ChatGenerationError("generation API key is required")
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ChatGenerationError(
            "stored generation API key cannot be decrypted"
        ) from exc


def get_managed_support_ai_provider(
    session: Session,
) -> SupportAIProviderSettingsRow | None:
    return session.get(SupportAIProviderSettingsRow, SETTINGS_ID)


def _environment_values() -> tuple[str, str, str, int, int, float, bool]:
    base_url = os.getenv("SUPPORT_AI_BASE_URL", "").strip()
    api_key = os.getenv("SUPPORT_AI_API_KEY", "").strip()
    model = os.getenv("SUPPORT_AI_MODEL", "").strip()
    try:
        timeout = int(os.getenv("SUPPORT_AI_TIMEOUT_SECONDS", "45"))
        max_tokens = int(os.getenv("SUPPORT_AI_MAX_OUTPUT_TOKENS", "2048"))
        temperature = float(os.getenv("SUPPORT_AI_TEMPERATURE", "0.1"))
    except ValueError as exc:
        raise ChatGenerationError("support AI environment settings are invalid") from exc
    enabled = os.getenv("SUPPORT_AI_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return base_url, api_key, model, timeout, max_tokens, temperature, enabled


def support_ai_provider_is_configured(session: Session) -> bool:
    settings = get_managed_support_ai_provider(session)
    if settings is not None:
        return bool(
            settings.is_active
            and settings.base_url.strip()
            and settings.model_name.strip()
            and settings.api_key_ciphertext
        )
    base_url, api_key, model, *_rest, enabled = _environment_values()
    return bool(enabled and base_url and api_key and model)


def support_ai_provider_snapshot(session: Session) -> SupportAIProviderSnapshot:
    settings = get_managed_support_ai_provider(session)
    if settings is not None:
        return SupportAIProviderSnapshot(
            source="database",
            provider=settings.provider,
            enabled=settings.is_active,
            base_url=settings.base_url,
            model_name=settings.model_name,
            timeout_seconds=settings.timeout_seconds,
            max_output_tokens=settings.max_output_tokens,
            temperature=float(settings.temperature),
            api_key_configured=bool(settings.api_key_ciphertext),
            api_key_hint=(
                f"••••{settings.api_key_last_four}"
                if settings.api_key_last_four
                else None
            ),
            updated_at=settings.updated_at,
        )
    base_url, api_key, model, timeout, max_tokens, temperature, enabled = (
        _environment_values()
    )
    if base_url and model and api_key:
        chat_completions_endpoint(base_url)
        return SupportAIProviderSnapshot(
            source="environment",
            provider="openai-compatible",
            enabled=enabled,
            base_url=base_url,
            model_name=model,
            timeout_seconds=timeout,
            max_output_tokens=max_tokens,
            temperature=temperature,
            api_key_configured=True,
            api_key_hint=f"••••{api_key[-4:]}",
            updated_at=None,
        )
    return SupportAIProviderSnapshot(
        source="disabled",
        provider="openai-compatible",
        enabled=False,
        base_url=None,
        model_name=None,
        timeout_seconds=45,
        max_output_tokens=2048,
        temperature=0.1,
        api_key_configured=False,
        api_key_hint=None,
        updated_at=None,
    )


def resolved_support_ai_provider(session: Session) -> ChatGenerationProvider:
    settings = get_managed_support_ai_provider(session)
    if settings is not None:
        if not settings.is_active:
            raise ChatGenerationError("support AI generation provider is disabled")
        return openai_compatible_chat_provider(
            api_key=decrypt_api_key(settings.api_key_ciphertext),
            base_url=settings.base_url,
            model_name=settings.model_name,
            timeout_seconds=float(settings.timeout_seconds),
            max_output_tokens=settings.max_output_tokens,
            temperature=float(settings.temperature),
        )
    base_url, api_key, model, timeout, max_tokens, temperature, enabled = (
        _environment_values()
    )
    if not enabled or not (base_url and api_key and model):
        raise ChatGenerationError("support AI generation provider is not configured")
    return openai_compatible_chat_provider(
        api_key=api_key,
        base_url=base_url,
        model_name=model,
        timeout_seconds=float(timeout),
        max_output_tokens=max_tokens,
        temperature=temperature,
    )


def save_managed_support_ai_provider(
    session: Session,
    *,
    enabled: bool,
    base_url: str,
    model_name: str,
    timeout_seconds: int,
    max_output_tokens: int,
    temperature: float,
    api_key: str | None,
    updated_by_user_id: UUID,
) -> SupportAIProviderSettingsRow:
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_model = model_name.strip()
    chat_completions_endpoint(normalized_base_url)
    if not normalized_model:
        raise ChatGenerationError("generation model is required")
    if timeout_seconds < 1 or timeout_seconds > 180:
        raise ChatGenerationError("generation timeout must be between 1 and 180 seconds")
    if max_output_tokens < 128 or max_output_tokens > 32768:
        raise ChatGenerationError(
            "generation max output tokens must be between 128 and 32768"
        )
    if temperature < 0 or temperature > 2:
        raise ChatGenerationError("generation temperature must be between 0 and 2")
    settings = get_managed_support_ai_provider(session)
    normalized_key = api_key.strip() if api_key is not None else ""
    if settings is None and not normalized_key:
        normalized_key = os.getenv("SUPPORT_AI_API_KEY", "").strip()
    if settings is None and not normalized_key:
        raise ChatGenerationError(
            "generation API key is required for the first configuration"
        )
    if settings is None:
        settings = SupportAIProviderSettingsRow(
            id=SETTINGS_ID,
            provider="openai-compatible",
            base_url=normalized_base_url,
            model_name=normalized_model,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            temperature=Decimal(str(temperature)),
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
        settings.timeout_seconds = timeout_seconds
        settings.max_output_tokens = max_output_tokens
        settings.temperature = Decimal(str(temperature))
        settings.is_active = enabled
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if normalized_key:
            settings.api_key_ciphertext = encrypt_api_key(normalized_key)
            settings.api_key_last_four = normalized_key[-4:]
    session.flush()
    return settings
