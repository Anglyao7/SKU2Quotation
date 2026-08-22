from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..image_generation_models import ImageGenerationProviderSettingsRow
from ..model_mixins import utcnow
from .image_generation_rate_limit import (
    DEFAULT_IMAGE_GENERATION_CONCURRENCY,
    DEFAULT_IMAGE_GENERATION_REQUESTS_PER_MINUTE,
    environment_image_generation_limits,
    normalized_image_generation_concurrency,
    normalized_image_generation_requests_per_minute,
)


SETTINGS_ID = "AGNES_IMAGE_GENERATION"
DEFAULT_IMAGE_GENERATION_BASE_URL = (
    "https://apihub.agnes-ai.com/v1/images/generations"
)
DEFAULT_IMAGE_GENERATION_MODEL = "agnes-image-2.0-flash"
DEFAULT_IMAGE_ENHANCEMENT_SYSTEM_PROMPT = (
    "Enhance only the provided product image: make it sharper, clearer, and less noisy. "
    "The input image is the source of truth. Preserve the exact product, colors, materials, "
    "shape, proportions, existing text, markings, existing logos, background, lighting, and composition. "
    "Do not add, remove, redraw, or invent any logo, text, label, accessory, decoration, prop, or other object. "
    "Do not change the background or create a new design."
)
IMAGE_ENHANCEMENT_SYSTEM_PROMPT_MAX_LENGTH = 12000


class ImageGenerationConfigurationError(ValueError):
    """A safe, user-facing image generation configuration error."""


@dataclass(frozen=True, slots=True)
class ImageGenerationConfigurationSnapshot:
    source: str
    provider: str
    enabled: bool
    base_url: str | None
    model_name: str | None
    system_prompt: str
    timeout_seconds: int
    requests_per_minute: int
    concurrency_limit: int
    api_key_configured: bool
    api_key_hint: str | None
    updated_at: datetime | None


def _master_secret() -> str:
    configured = os.getenv("IMAGE_GENERATION_SETTINGS_MASTER_KEY", "").strip()
    secret = configured or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
    managed = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    if configured and managed and len(configured) < 32:
        raise ImageGenerationConfigurationError(
            "image generation settings encryption key must contain at least 32 characters"
        )
    if secret:
        return secret
    if managed:
        raise ImageGenerationConfigurationError(
            "image generation settings encryption key is not configured"
        )
    return "local-development-only-image-generation-settings-key"


def _fernet() -> Fernet:
    material = hashlib.sha256(
        f"atc:image-generation-settings:v1:{_master_secret()}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if not normalized:
        raise ImageGenerationConfigurationError(
            "image generation API key is required"
        )
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise ImageGenerationConfigurationError(
            "stored image generation API key cannot be decrypted"
        ) from exc


def image_generation_endpoint(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    production = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }
    allowed_schemes = {"https"} if production else {"http", "https"}
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ImageGenerationConfigurationError(
            "image generation endpoint must be a valid HTTP(S) URL"
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1/images/generations"):
        raise ImageGenerationConfigurationError(
            "image generation endpoint must end with /v1/images/generations"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _environment_system_prompt() -> str:
    return (
        os.getenv("AGNES_IMAGE_ENHANCEMENT_SYSTEM_PROMPT", "").strip()
        or DEFAULT_IMAGE_ENHANCEMENT_SYSTEM_PROMPT
    )


def image_enhancement_system_prompt(session: Session) -> str:
    """Return the single platform-managed prompt used for first attempts."""

    settings = get_managed_image_generation_settings(session)
    if settings is not None and settings.system_prompt.strip():
        return settings.system_prompt.strip()
    return _environment_system_prompt()


def _environment_values() -> tuple[str, str, str, int, int, int, bool]:
    base_url = (
        os.getenv("AGNES_IMAGE_GENERATION_BASE_URL", "").strip()
        or os.getenv("AGNES_IMAGE_BASE_URL", "").strip()
    )
    api_key = (
        os.getenv("AGNES_IMAGE_GENERATION_API_KEY", "").strip()
        or os.getenv("AGNES_IMAGE_API_KEY", "").strip()
    )
    model_name = (
        os.getenv("AGNES_IMAGE_GENERATION_MODEL", "").strip()
        or os.getenv("AGNES_IMAGE_MODEL", "").strip()
    )
    try:
        timeout_seconds = int(
            os.getenv("AGNES_IMAGE_GENERATION_TIMEOUT_SECONDS", "180")
        )
    except ValueError as exc:
        raise ImageGenerationConfigurationError(
            "image generation timeout must be an integer"
        ) from exc
    enabled = os.getenv("AGNES_IMAGE_GENERATION_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    try:
        requests_per_minute, concurrency_limit = environment_image_generation_limits()
    except ValueError as exc:
        raise ImageGenerationConfigurationError(str(exc)) from exc
    return (
        base_url,
        api_key,
        model_name,
        timeout_seconds,
        requests_per_minute,
        concurrency_limit,
        enabled,
    )


def get_managed_image_generation_settings(
    session: Session,
) -> ImageGenerationProviderSettingsRow | None:
    row = session.get(ImageGenerationProviderSettingsRow, SETTINGS_ID)
    return row if row is not None and row.deleted_at is None else None


def image_generation_configuration_snapshot(
    session: Session,
) -> ImageGenerationConfigurationSnapshot:
    settings = get_managed_image_generation_settings(session)
    if settings is not None:
        return ImageGenerationConfigurationSnapshot(
            source="database",
            provider=settings.provider,
            enabled=settings.is_active,
            base_url=settings.base_url,
            model_name=settings.model_name,
            system_prompt=(settings.system_prompt.strip() or DEFAULT_IMAGE_ENHANCEMENT_SYSTEM_PROMPT),
            timeout_seconds=settings.timeout_seconds,
            requests_per_minute=settings.requests_per_minute,
            concurrency_limit=settings.concurrency_limit,
            api_key_configured=bool(settings.api_key_ciphertext),
            api_key_hint=(
                f"••••{settings.api_key_last_four}"
                if settings.api_key_last_four
                else None
            ),
            updated_at=settings.updated_at,
        )

    (
        base_url,
        api_key,
        model_name,
        timeout_seconds,
        requests_per_minute,
        concurrency_limit,
        enabled,
    ) = _environment_values()
    if base_url and api_key and model_name:
        return ImageGenerationConfigurationSnapshot(
            source="environment",
            provider="agnes-ai",
            enabled=enabled,
            base_url=image_generation_endpoint(base_url),
            model_name=model_name,
            system_prompt=_environment_system_prompt(),
            timeout_seconds=timeout_seconds,
            requests_per_minute=requests_per_minute,
            concurrency_limit=concurrency_limit,
            api_key_configured=True,
            api_key_hint=f"••••{api_key[-4:]}",
            updated_at=None,
        )
    return ImageGenerationConfigurationSnapshot(
        source="disabled",
        provider="agnes-ai",
        enabled=False,
        base_url=base_url or DEFAULT_IMAGE_GENERATION_BASE_URL,
        model_name=model_name or DEFAULT_IMAGE_GENERATION_MODEL,
        system_prompt=_environment_system_prompt(),
        timeout_seconds=timeout_seconds,
        requests_per_minute=requests_per_minute,
        concurrency_limit=concurrency_limit,
        api_key_configured=bool(api_key),
        api_key_hint=f"••••{api_key[-4:]}" if api_key else None,
        updated_at=None,
    )


def save_managed_image_generation_settings(
    session: Session,
    *,
    enabled: bool,
    base_url: str,
    model_name: str,
    timeout_seconds: int,
    api_key: str | None,
    updated_by_user_id,
    system_prompt: str | None = None,
    requests_per_minute: int = DEFAULT_IMAGE_GENERATION_REQUESTS_PER_MINUTE,
    concurrency_limit: int = DEFAULT_IMAGE_GENERATION_CONCURRENCY,
) -> ImageGenerationProviderSettingsRow:
    normalized_base_url = image_generation_endpoint(base_url)
    normalized_model_name = model_name.strip()
    if not normalized_model_name:
        raise ImageGenerationConfigurationError("image generation model is required")
    normalized_system_prompt = (system_prompt or "").strip() or _environment_system_prompt()
    if len(normalized_system_prompt) > IMAGE_ENHANCEMENT_SYSTEM_PROMPT_MAX_LENGTH:
        raise ImageGenerationConfigurationError(
            "image enhancement system prompt is too long"
        )
    if timeout_seconds < 60 or timeout_seconds > 360:
        raise ImageGenerationConfigurationError(
            "image generation timeout must be between 60 and 360 seconds"
        )
    try:
        normalized_rpm = normalized_image_generation_requests_per_minute(
            requests_per_minute
        )
        normalized_concurrency = normalized_image_generation_concurrency(
            concurrency_limit
        )
    except ValueError as exc:
        raise ImageGenerationConfigurationError(str(exc)) from exc
    settings = get_managed_image_generation_settings(session)
    normalized_key = api_key.strip() if api_key is not None else ""
    if settings is None and not normalized_key:
        _base_url, env_key, _model, _timeout, _rpm, _concurrency, _enabled = (
            _environment_values()
        )
        normalized_key = env_key
    if settings is None and not normalized_key:
        raise ImageGenerationConfigurationError(
            "image generation API key is required for the first configuration"
        )
    if settings is None:
        settings = ImageGenerationProviderSettingsRow(
            id=SETTINGS_ID,
            provider="agnes-ai",
            base_url=normalized_base_url,
            model_name=normalized_model_name,
            system_prompt=normalized_system_prompt,
            timeout_seconds=timeout_seconds,
            requests_per_minute=normalized_rpm,
            concurrency_limit=normalized_concurrency,
            api_key_ciphertext=encrypt_api_key(normalized_key),
            api_key_last_four=normalized_key[-4:] or None,
            is_active=enabled,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(settings)
    else:
        settings.base_url = normalized_base_url
        settings.model_name = normalized_model_name
        settings.system_prompt = normalized_system_prompt
        settings.timeout_seconds = timeout_seconds
        settings.requests_per_minute = normalized_rpm
        settings.concurrency_limit = normalized_concurrency
        settings.is_active = enabled
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if normalized_key:
            settings.api_key_ciphertext = encrypt_api_key(normalized_key)
            settings.api_key_last_four = normalized_key[-4:]
    session.flush()
    return settings
