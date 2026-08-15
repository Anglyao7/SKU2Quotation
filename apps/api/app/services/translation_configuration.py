from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..model_mixins import utcnow
from ..translation_management_models import TranslationProviderSettingsRow
from .translation import (
    DEFAULT_ALIYUN_ALIMT_ENDPOINT,
    DEFAULT_ALIYUN_ALIMT_REGION,
    TranslationProvider,
    TranslationProviderError,
    _aliyun_endpoint,
    _deeplx_endpoint,
    _openai_chat_completions_endpoint,
    aliyun_alimt_translation_provider,
    deeplx_translation_provider,
    openai_compatible_translation_provider,
)
from .translation_rate_limit import (
    environment_translation_requests_per_minute,
    normalized_translation_requests_per_minute,
    rate_limited_translation_provider,
)


SETTINGS_ID = "CATALOG_TRANSLATION"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_TOKENS = 16_384
DEFAULT_MAX_RETRY_COUNT = 3
DEFAULT_CATALOG_BATCH_SIZE = 50
DEFAULT_CATALOG_BATCH_CHARACTERS = 10_000
MAX_CATALOG_BATCH_SIZE = 200
MIN_CATALOG_BATCH_CHARACTERS = 1_000
MAX_CATALOG_BATCH_CHARACTERS = 100_000
MAX_TRANSLATION_RETRY_COUNT = 10
DEFAULT_REASONING_EFFORT = "low"
SUPPORTED_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high"}
SUPPORTED_PROVIDERS = {"openai-compatible", "deeplx", "aliyun-alimt"}
ALIYUN_GENERAL_EDITION = "translate_standard"


@dataclass(frozen=True)
class TranslationConfigurationSnapshot:
    source: str
    provider: str
    enabled: bool
    base_url: str | None
    model_name: str | None
    region_id: str | None
    timeout_seconds: int
    max_tokens: int
    requests_per_minute: int
    max_retry_count: int
    catalog_batch_size: int
    catalog_batch_characters: int
    reasoning_effort: str
    api_key_configured: bool
    api_key_hint: str | None
    access_key_id_configured: bool
    access_key_id_hint: str | None
    updated_at: datetime | None


def _managed_environment() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "staging",
    }


def _master_secret() -> str:
    configured_secret = os.getenv("TRANSLATION_SETTINGS_MASTER_KEY", "").strip()
    secret = configured_secret or os.getenv("AUTH_TOKEN_PEPPER", "").strip()
    if configured_secret and _managed_environment() and len(configured_secret) < 32:
        raise TranslationProviderError(
            "translation settings encryption key must contain at least 32 characters"
        )
    if secret:
        return secret
    if _managed_environment():
        raise TranslationProviderError(
            "translation settings encryption key is not configured"
        )
    return "local-development-only-translation-settings-key"


def _fernet() -> Fernet:
    material = hashlib.sha256(
        f"atc:translation-settings:v1:{_master_secret()}".encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt_translation_api_key(api_key: str) -> str:
    normalized = api_key.strip()
    if not normalized:
        raise TranslationProviderError("translation API key is required")
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_translation_api_key(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise TranslationProviderError(
            "stored translation API key cannot be decrypted"
        ) from exc


def _normalized_reasoning_effort(value: str) -> str:
    normalized = value.strip().lower() or DEFAULT_REASONING_EFFORT
    if normalized not in SUPPORTED_REASONING_EFFORTS:
        raise TranslationProviderError(
            "translation reasoning effort must be none, minimal, low, medium, or high"
        )
    return normalized


def _normalized_provider(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized not in SUPPORTED_PROVIDERS:
        raise TranslationProviderError(
            "translation provider must be openai-compatible, deeplx, or aliyun-alimt"
        )
    return normalized


def _redacted_deeplx_endpoint(endpoint: str) -> str:
    """Keep the token-bearing path out of the plaintext settings column."""

    parsed = urlsplit(endpoint)
    return urlunsplit((parsed.scheme, parsed.netloc, "/translate", "", ""))


def normalized_catalog_translation_batch_limits(
    batch_size: int,
    batch_characters: int,
) -> tuple[int, int]:
    if batch_size < 1 or batch_size > MAX_CATALOG_BATCH_SIZE:
        raise TranslationProviderError(
            "catalog translation batch size must be between 1 and 200"
        )
    if (
        batch_characters < MIN_CATALOG_BATCH_CHARACTERS
        or batch_characters > MAX_CATALOG_BATCH_CHARACTERS
    ):
        raise TranslationProviderError(
            "catalog translation batch characters must be between 1000 and 100000"
        )
    return batch_size, batch_characters


def _environment_catalog_translation_batch_limits() -> tuple[int, int]:
    try:
        batch_size = int(
            os.getenv(
                "CATALOG_TRANSLATION_BATCH_SIZE",
                str(DEFAULT_CATALOG_BATCH_SIZE),
            )
        )
        batch_characters = int(
            os.getenv(
                "CATALOG_TRANSLATION_BATCH_CHARACTERS",
                str(DEFAULT_CATALOG_BATCH_CHARACTERS),
            )
        )
    except ValueError as exc:
        raise TranslationProviderError(
            "catalog translation batch limits must be integers"
        ) from exc
    return normalized_catalog_translation_batch_limits(
        batch_size,
        batch_characters,
    )


def normalized_catalog_translation_retry_count(value: int) -> int:
    if value < 0 or value > MAX_TRANSLATION_RETRY_COUNT:
        raise TranslationProviderError(
            "catalog translation retry count must be between 0 and 10"
        )
    return value


def _environment_catalog_translation_retry_count() -> int:
    try:
        value = int(
            os.getenv(
                "CATALOG_TRANSLATION_PROVIDER_RETRIES",
                str(DEFAULT_MAX_RETRY_COUNT),
            )
        )
    except ValueError as exc:
        raise TranslationProviderError(
            "catalog translation retry count must be an integer"
        ) from exc
    return normalized_catalog_translation_retry_count(value)


def _validated_provider(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    access_key_id: str | None,
    model_name: str,
    region_id: str | None,
    timeout_seconds: int,
    max_tokens: int,
    reasoning_effort: str,
) -> TranslationProvider:
    normalized_provider = _normalized_provider(provider)
    normalized_base_url = base_url.strip().rstrip("/")
    normalized_model = model_name.strip()
    if normalized_provider == "deeplx":
        return deeplx_translation_provider(
            endpoint=api_key,
            timeout_seconds=float(timeout_seconds),
            production=_managed_environment(),
        )
    if normalized_provider == "aliyun-alimt":
        if normalized_model != ALIYUN_GENERAL_EDITION:
            raise TranslationProviderError(
                "Aliyun translation edition must be translate_standard"
            )
        return aliyun_alimt_translation_provider(
            access_key_id=(access_key_id or "").strip(),
            access_key_secret=api_key,
            region_id=(region_id or DEFAULT_ALIYUN_ALIMT_REGION).strip(),
            endpoint=_aliyun_endpoint(normalized_base_url),
            timeout_seconds=float(timeout_seconds),
        )
    _openai_chat_completions_endpoint(
        normalized_base_url,
        production=_managed_environment(),
    )
    if not normalized_model:
        raise TranslationProviderError("translation model is required")
    return openai_compatible_translation_provider(
        normalized_base_url,
        api_key,
        normalized_model,
        float(timeout_seconds),
        max_tokens,
        _normalized_reasoning_effort(reasoning_effort),
        _managed_environment(),
    )


def get_managed_translation_settings(
    session: Session,
) -> TranslationProviderSettingsRow | None:
    return session.get(TranslationProviderSettingsRow, SETTINGS_ID)


def _environment_provider() -> str | None:
    profile = os.getenv("CATALOG_TRANSLATION_PROFILE", "disabled").strip().lower()
    if profile == "deeplx":
        return "deeplx"
    if profile == "openai_compatible":
        return "openai-compatible"
    if profile == "aliyun_alimt":
        return "aliyun-alimt"
    return None


def _environment_api_key(provider: str) -> str:
    if _environment_provider() != provider:
        return ""
    variable = (
        "DEEPLX_TRANSLATE_URL"
        if provider == "deeplx"
        else (
            "ALIYUN_TRANSLATION_ACCESS_KEY_SECRET"
            if provider == "aliyun-alimt"
            else "OPENAI_TRANSLATION_API_KEY"
        )
    )
    return os.getenv(variable, "").strip()


def _environment_access_key_id(provider: str) -> str:
    if provider != "aliyun-alimt" or _environment_provider() != provider:
        return ""
    return os.getenv("ALIYUN_TRANSLATION_ACCESS_KEY_ID", "").strip()


def _environment_snapshot() -> TranslationConfigurationSnapshot:
    catalog_batch_size, catalog_batch_characters = (
        _environment_catalog_translation_batch_limits()
    )
    profile = os.getenv("CATALOG_TRANSLATION_PROFILE", "disabled").strip().lower()
    if profile in {"", "disabled", "none"}:
        return TranslationConfigurationSnapshot(
            source="disabled",
            provider="openai-compatible",
            enabled=False,
            base_url=None,
            model_name=None,
            region_id=None,
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            max_tokens=DEFAULT_MAX_TOKENS,
            requests_per_minute=environment_translation_requests_per_minute(),
            max_retry_count=_environment_catalog_translation_retry_count(),
            catalog_batch_size=catalog_batch_size,
            catalog_batch_characters=catalog_batch_characters,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
            api_key_configured=False,
            api_key_hint=None,
            access_key_id_configured=False,
            access_key_id_hint=None,
            updated_at=None,
        )
    if profile == "deeplx":
        try:
            timeout_seconds = int(float(os.getenv("DEEPLX_TIMEOUT_SECONDS", "20")))
        except ValueError as exc:
            raise TranslationProviderError(
                "DEEPLX_TIMEOUT_SECONDS must be a number"
            ) from exc
        configured = bool(os.getenv("DEEPLX_TRANSLATE_URL", "").strip())
        return TranslationConfigurationSnapshot(
            source="environment",
            provider="deeplx",
            enabled=configured,
            # A DeepLX token can be embedded in this URL, so never return it.
            base_url=None,
            model_name="DeepLX",
            region_id=None,
            timeout_seconds=timeout_seconds,
            max_tokens=DEFAULT_MAX_TOKENS,
            requests_per_minute=environment_translation_requests_per_minute(),
            max_retry_count=_environment_catalog_translation_retry_count(),
            catalog_batch_size=catalog_batch_size,
            catalog_batch_characters=catalog_batch_characters,
            reasoning_effort="none",
            api_key_configured=configured,
            api_key_hint=None,
            access_key_id_configured=False,
            access_key_id_hint=None,
            updated_at=None,
        )
    if profile == "aliyun_alimt":
        raw_api_key = _environment_api_key("aliyun-alimt")
        access_key_id = _environment_access_key_id("aliyun-alimt")
        try:
            timeout_seconds = int(
                float(os.getenv("ALIYUN_TRANSLATION_TIMEOUT_SECONDS", "20"))
            )
        except ValueError as exc:
            raise TranslationProviderError(
                "ALIYUN_TRANSLATION_TIMEOUT_SECONDS must be a number"
            ) from exc
        return TranslationConfigurationSnapshot(
            source="environment",
            provider="aliyun-alimt",
            enabled=bool(raw_api_key and access_key_id),
            base_url=os.getenv(
                "ALIYUN_TRANSLATION_ENDPOINT",
                DEFAULT_ALIYUN_ALIMT_ENDPOINT,
            ).strip(),
            model_name=ALIYUN_GENERAL_EDITION,
            region_id=os.getenv(
                "ALIYUN_TRANSLATION_REGION_ID",
                DEFAULT_ALIYUN_ALIMT_REGION,
            ).strip(),
            timeout_seconds=timeout_seconds,
            max_tokens=DEFAULT_MAX_TOKENS,
            requests_per_minute=environment_translation_requests_per_minute(),
            max_retry_count=_environment_catalog_translation_retry_count(),
            catalog_batch_size=catalog_batch_size,
            catalog_batch_characters=catalog_batch_characters,
            reasoning_effort="none",
            api_key_configured=bool(raw_api_key),
            api_key_hint=f"••••{raw_api_key[-4:]}" if raw_api_key else None,
            access_key_id_configured=bool(access_key_id),
            access_key_id_hint=(
                f"••••{access_key_id[-4:]}" if access_key_id else None
            ),
            updated_at=None,
        )
    if profile != "openai_compatible":
        raise TranslationProviderError(
            f"unsupported CATALOG_TRANSLATION_PROFILE: {profile}"
        )
    raw_api_key = _environment_api_key("openai-compatible")
    try:
        timeout_seconds = int(
            float(os.getenv("OPENAI_TRANSLATION_TIMEOUT_SECONDS", "20"))
        )
        max_tokens = int(os.getenv("OPENAI_TRANSLATION_MAX_TOKENS", "16384"))
    except ValueError as exc:
        raise TranslationProviderError(
            "translation timeout and max tokens must be numbers"
        ) from exc
    return TranslationConfigurationSnapshot(
        source="environment",
        provider="openai-compatible",
        enabled=bool(
            os.getenv("OPENAI_TRANSLATION_BASE_URL", "").strip()
            and raw_api_key
            and os.getenv("OPENAI_TRANSLATION_MODEL", "").strip()
        ),
        base_url=os.getenv("OPENAI_TRANSLATION_BASE_URL", "").strip() or None,
        model_name=os.getenv("OPENAI_TRANSLATION_MODEL", "").strip() or None,
        region_id=None,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        requests_per_minute=environment_translation_requests_per_minute(),
        max_retry_count=_environment_catalog_translation_retry_count(),
        catalog_batch_size=catalog_batch_size,
        catalog_batch_characters=catalog_batch_characters,
        reasoning_effort=_normalized_reasoning_effort(
            os.getenv(
                "OPENAI_TRANSLATION_REASONING_EFFORT",
                DEFAULT_REASONING_EFFORT,
            )
        ),
        api_key_configured=bool(raw_api_key),
        api_key_hint=f"••••{raw_api_key[-4:]}" if raw_api_key else None,
        access_key_id_configured=False,
        access_key_id_hint=None,
        updated_at=None,
    )


def translation_configuration_snapshot(
    session: Session,
) -> TranslationConfigurationSnapshot:
    settings = get_managed_translation_settings(session)
    if settings is None:
        return _environment_snapshot()
    return TranslationConfigurationSnapshot(
        source="database",
        provider=settings.provider,
        enabled=settings.is_active,
        # DeepLX endpoints commonly include the access token in the path.
        base_url=None if settings.provider == "deeplx" else settings.base_url,
        model_name=settings.model_name,
        region_id=settings.region_id,
        timeout_seconds=settings.timeout_seconds,
        max_tokens=settings.max_tokens,
        requests_per_minute=settings.requests_per_minute,
        max_retry_count=settings.max_retry_count,
        catalog_batch_size=settings.catalog_batch_size,
        catalog_batch_characters=settings.catalog_batch_characters,
        reasoning_effort=settings.reasoning_effort,
        api_key_configured=bool(settings.api_key_ciphertext),
        api_key_hint=(
            f"••••{settings.api_key_last_four}"
            if settings.provider != "deeplx" and settings.api_key_last_four
            else None
        ),
        access_key_id_configured=bool(settings.access_key_id_ciphertext),
        access_key_id_hint=(
            f"••••{settings.access_key_id_last_four}"
            if settings.access_key_id_last_four
            else None
        ),
        updated_at=settings.updated_at,
    )


def resolved_catalog_translation_batch_limits(
    session: Session,
) -> tuple[int, int]:
    """Resolve the platform-managed SKU and character limits for one job."""

    settings = get_managed_translation_settings(session)
    if settings is None:
        return _environment_catalog_translation_batch_limits()
    return normalized_catalog_translation_batch_limits(
        settings.catalog_batch_size,
        settings.catalog_batch_characters,
    )


def resolved_catalog_translation_retry_count(session: Session) -> int:
    """Resolve how many retries follow the first failed provider request."""

    settings = get_managed_translation_settings(session)
    if settings is None:
        return _environment_catalog_translation_retry_count()
    return normalized_catalog_translation_retry_count(settings.max_retry_count)


def translation_provider_is_configured(
    session: Session,
    *,
    environment_check: Callable[[], bool],
) -> bool:
    settings = get_managed_translation_settings(session)
    if settings is None:
        return environment_check()
    if not settings.is_active or not settings.api_key_ciphertext:
        return False
    if settings.provider == "aliyun-alimt":
        return bool(settings.access_key_id_ciphertext)
    return True


def resolved_catalog_translator(
    session: Session,
    *,
    environment_factory: Callable[[], TranslationProvider],
) -> TranslationProvider:
    settings = get_managed_translation_settings(session)
    if settings is None:
        return rate_limited_translation_provider(
            environment_factory(),
            requests_per_minute=environment_translation_requests_per_minute(),
        )
    if not settings.is_active:
        raise TranslationProviderError("catalog translation provider is disabled")
    if not settings.api_key_ciphertext:
        raise TranslationProviderError("translation API key is not configured")
    access_key_id = (
        decrypt_translation_api_key(settings.access_key_id_ciphertext)
        if settings.access_key_id_ciphertext
        else None
    )
    return rate_limited_translation_provider(
        _validated_provider(
            provider=settings.provider,
            base_url=settings.base_url,
            api_key=decrypt_translation_api_key(settings.api_key_ciphertext),
            access_key_id=access_key_id,
            model_name=settings.model_name,
            region_id=settings.region_id,
            timeout_seconds=settings.timeout_seconds,
            max_tokens=settings.max_tokens,
            reasoning_effort=settings.reasoning_effort,
        ),
        requests_per_minute=settings.requests_per_minute,
    )


def _resolved_api_key(
    session: Session,
    *,
    provider: str,
    api_key: str | None,
) -> str:
    normalized_key = (api_key or "").strip()
    if normalized_key:
        return normalized_key
    settings = get_managed_translation_settings(session)
    if (
        settings is not None
        and settings.provider == provider
        and settings.api_key_ciphertext
    ):
        return decrypt_translation_api_key(settings.api_key_ciphertext)
    return _environment_api_key(provider)


def _resolved_access_key_id(
    session: Session,
    *,
    provider: str,
    access_key_id: str | None,
) -> str:
    normalized_key = (access_key_id or "").strip()
    if normalized_key:
        return normalized_key
    settings = get_managed_translation_settings(session)
    if (
        settings is not None
        and settings.provider == provider
        and settings.access_key_id_ciphertext
    ):
        return decrypt_translation_api_key(settings.access_key_id_ciphertext)
    return _environment_access_key_id(provider)


def candidate_translation_provider(
    session: Session,
    *,
    provider: str,
    base_url: str,
    api_key: str | None,
    access_key_id: str | None,
    model_name: str,
    region_id: str | None,
    timeout_seconds: int,
    max_tokens: int,
    requests_per_minute: int,
    reasoning_effort: str,
) -> TranslationProvider:
    normalized_translation_requests_per_minute(requests_per_minute)
    normalized_provider = _normalized_provider(provider)
    resolved_key = (
        base_url.strip()
        if normalized_provider == "deeplx" and base_url.strip()
        else _resolved_api_key(
            session,
            provider=normalized_provider,
            api_key=api_key,
        )
    )
    if not resolved_key:
        raise TranslationProviderError(
            "translation API key or AccessKey Secret is required for the first configuration"
        )
    resolved_access_key_id = _resolved_access_key_id(
        session,
        provider=normalized_provider,
        access_key_id=access_key_id,
    )
    if normalized_provider == "aliyun-alimt" and not resolved_access_key_id:
        raise TranslationProviderError(
            "Aliyun AccessKey ID is required for the first configuration"
        )
    return _validated_provider(
        provider=normalized_provider,
        base_url=base_url,
        api_key=resolved_key,
        access_key_id=resolved_access_key_id,
        model_name=model_name,
        region_id=region_id,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )


def save_managed_translation_settings(
    session: Session,
    *,
    provider: str,
    base_url: str,
    model_name: str,
    region_id: str | None,
    timeout_seconds: int,
    max_tokens: int,
    requests_per_minute: int,
    max_retry_count: int,
    catalog_batch_size: int,
    catalog_batch_characters: int,
    reasoning_effort: str,
    api_key: str | None,
    access_key_id: str | None,
    enabled: bool,
    updated_by_user_id: UUID,
) -> TranslationProviderSettingsRow:
    normalized_provider = _normalized_provider(provider)
    normalized_rpm = normalized_translation_requests_per_minute(
        requests_per_minute
    )
    normalized_retry_count = normalized_catalog_translation_retry_count(
        max_retry_count
    )
    normalized_batch_size, normalized_batch_characters = (
        normalized_catalog_translation_batch_limits(
            catalog_batch_size,
            catalog_batch_characters,
        )
    )
    settings = get_managed_translation_settings(session)
    provider_changed = bool(
        settings is not None and settings.provider != normalized_provider
    )
    resolved_key = (
        base_url.strip()
        if normalized_provider == "deeplx" and base_url.strip()
        else _resolved_api_key(
            session,
            provider=normalized_provider,
            api_key=api_key,
        )
    )
    if normalized_provider == "deeplx":
        if not resolved_key:
            raise TranslationProviderError(
                "DeepLX translation endpoint is required for the first configuration"
            )
        endpoint = _deeplx_endpoint(
            resolved_key,
            production=_managed_environment(),
        )
        resolved_key = endpoint
        normalized_base_url = _redacted_deeplx_endpoint(endpoint)
        normalized_model = "DeepLX"
        normalized_region = None
        normalized_reasoning = "none"
    elif normalized_provider == "aliyun-alimt":
        normalized_base_url = _aliyun_endpoint(base_url)
        normalized_model = ALIYUN_GENERAL_EDITION
        normalized_region = (
            (region_id or DEFAULT_ALIYUN_ALIMT_REGION).strip()
            or DEFAULT_ALIYUN_ALIMT_REGION
        )
        normalized_reasoning = "none"
    else:
        normalized_base_url = base_url.strip().rstrip("/")
        normalized_model = model_name.strip()
        normalized_region = None
        normalized_reasoning = _normalized_reasoning_effort(reasoning_effort)
        _openai_chat_completions_endpoint(
            normalized_base_url,
            production=_managed_environment(),
        )
        if not normalized_model:
            raise TranslationProviderError("translation model is required")

    resolved_access_key_id = _resolved_access_key_id(
        session,
        provider=normalized_provider,
        access_key_id=access_key_id,
    )
    if enabled and not resolved_key:
        raise TranslationProviderError(
            "translation API key or AccessKey Secret is required for the first configuration"
        )
    if (
        enabled
        and normalized_provider == "aliyun-alimt"
        and not resolved_access_key_id
    ):
        raise TranslationProviderError(
            "Aliyun AccessKey ID is required for the first configuration"
        )
    if enabled:
        _validated_provider(
            provider=normalized_provider,
            base_url=normalized_base_url,
            api_key=resolved_key,
            access_key_id=resolved_access_key_id,
            model_name=normalized_model,
            region_id=normalized_region,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            reasoning_effort=normalized_reasoning,
        )

    normalized_input_key = (
        base_url.strip()
        if normalized_provider == "deeplx"
        else (api_key or "").strip()
    )
    normalized_input_access_key_id = (access_key_id or "").strip()
    should_store_key = bool(normalized_input_key) or bool(
        resolved_key
        and (
            settings is None
            or provider_changed
            or not settings.api_key_ciphertext
        )
    )
    should_store_access_key_id = bool(normalized_input_access_key_id) or bool(
        resolved_access_key_id
        and (
            settings is None
            or provider_changed
            or not settings.access_key_id_ciphertext
        )
    )
    if settings is None:
        settings = TranslationProviderSettingsRow(
            id=SETTINGS_ID,
            provider=normalized_provider,
            base_url=normalized_base_url,
            model_name=normalized_model,
            region_id=normalized_region,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            requests_per_minute=normalized_rpm,
            max_retry_count=normalized_retry_count,
            catalog_batch_size=normalized_batch_size,
            catalog_batch_characters=normalized_batch_characters,
            reasoning_effort=normalized_reasoning,
            api_key_ciphertext=(
                encrypt_translation_api_key(resolved_key)
                if should_store_key
                else None
            ),
            api_key_last_four=(
                resolved_key[-4:]
                if should_store_key and normalized_provider != "deeplx"
                else None
            ),
            access_key_id_ciphertext=(
                encrypt_translation_api_key(resolved_access_key_id)
                if should_store_access_key_id
                else None
            ),
            access_key_id_last_four=(
                resolved_access_key_id[-4:]
                if should_store_access_key_id
                else None
            ),
            is_active=enabled,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(settings)
    else:
        if provider_changed:
            settings.api_key_ciphertext = None
            settings.api_key_last_four = None
            settings.access_key_id_ciphertext = None
            settings.access_key_id_last_four = None
        settings.provider = normalized_provider
        settings.base_url = normalized_base_url
        settings.model_name = normalized_model
        settings.region_id = normalized_region
        settings.timeout_seconds = timeout_seconds
        settings.max_tokens = max_tokens
        settings.requests_per_minute = normalized_rpm
        settings.max_retry_count = normalized_retry_count
        settings.catalog_batch_size = normalized_batch_size
        settings.catalog_batch_characters = normalized_batch_characters
        settings.reasoning_effort = normalized_reasoning
        settings.is_active = enabled
        settings.version += 1
        settings.updated_by_user_id = updated_by_user_id
        settings.updated_at = utcnow()
        if should_store_key:
            settings.api_key_ciphertext = encrypt_translation_api_key(
                resolved_key
            )
            settings.api_key_last_four = (
                resolved_key[-4:]
                if normalized_provider != "deeplx"
                else None
            )
        if normalized_provider != "aliyun-alimt":
            settings.access_key_id_ciphertext = None
            settings.access_key_id_last_four = None
        elif should_store_access_key_id:
            settings.access_key_id_ciphertext = encrypt_translation_api_key(
                resolved_access_key_id
            )
            settings.access_key_id_last_four = resolved_access_key_id[-4:]
    session.flush()
    return settings
