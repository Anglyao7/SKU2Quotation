from dataclasses import asdict
from time import monotonic

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import RequestContext
from ..services.translation import TranslationProviderError
from ..services.translation_configuration import (
    candidate_translation_provider,
    save_managed_translation_settings,
    translation_configuration_snapshot,
)
from ..services.translation_rate_limit import (
    configure_translation_requests_per_minute,
    rate_limited_translation_provider,
)
from ..translation_management_schemas import (
    TranslationSettingsResponse,
    TranslationSettingsTestRequest,
    TranslationSettingsTestResponse,
    TranslationSettingsUpdateRequest,
)


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def get_settings(
    session: Session,
    *,
    context: RequestContext,
) -> TranslationSettingsResponse:
    _require_platform_admin(context)
    try:
        snapshot = translation_configuration_snapshot(session)
    except (ValueError, TranslationProviderError) as exc:
        raise ApplicationError(
            "TRANSLATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    return TranslationSettingsResponse(**asdict(snapshot))


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: TranslationSettingsUpdateRequest,
) -> TranslationSettingsResponse:
    _require_platform_admin(context)
    try:
        save_managed_translation_settings(
            session,
            provider=request.provider,
            base_url=request.base_url,
            model_name=request.model_name,
            region_id=request.region_id,
            timeout_seconds=request.timeout_seconds,
            max_tokens=request.max_tokens,
            requests_per_minute=request.requests_per_minute,
            max_retry_count=request.max_retry_count,
            catalog_batch_size=request.catalog_batch_size,
            catalog_batch_characters=request.catalog_batch_characters,
            catalog_concurrency=request.catalog_concurrency,
            reasoning_effort=request.reasoning_effort,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            access_key_id=(
                request.access_key_id.get_secret_value()
                if request.access_key_id is not None
                else None
            ),
            enabled=request.enabled,
            updated_by_user_id=context.user_id,
        )
        session.commit()
        configure_translation_requests_per_minute(
            request.requests_per_minute
        )
        snapshot = translation_configuration_snapshot(session)
    except (ValueError, TranslationProviderError) as exc:
        session.rollback()
        raise ApplicationError(
            "TRANSLATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    return TranslationSettingsResponse(**asdict(snapshot))


def test_settings(
    session: Session,
    *,
    context: RequestContext,
    request: TranslationSettingsTestRequest,
) -> TranslationSettingsTestResponse:
    _require_platform_admin(context)
    try:
        provider = rate_limited_translation_provider(
            candidate_translation_provider(
                session,
                provider=request.provider,
                base_url=request.base_url,
                api_key=(
                    request.api_key.get_secret_value()
                    if request.api_key is not None
                    else None
                ),
                access_key_id=(
                    request.access_key_id.get_secret_value()
                    if request.access_key_id is not None
                    else None
                ),
                model_name=request.model_name,
                region_id=request.region_id,
                timeout_seconds=request.timeout_seconds,
                max_tokens=request.max_tokens,
                requests_per_minute=request.requests_per_minute,
                reasoning_effort=request.reasoning_effort,
            ),
            requests_per_minute=request.requests_per_minute,
            synchronize_limit=False,
        )
        started_at = monotonic()
        translated = provider.translate(
            "智能宠物喂食器 SF-6L20",
            source_locale="zh-CN",
            target_locale="en-US",
        ).strip()
        latency_ms = max(0, round((monotonic() - started_at) * 1000))
        if not translated:
            raise TranslationProviderError(
                "translation provider returned an empty translation"
            )
    except TranslationProviderError as exc:
        raise ApplicationError(
            "TRANSLATION_CONNECTION_TEST_FAILED",
            str(exc),
            kind="unavailable",
        ) from exc
    except Exception as exc:
        raise ApplicationError(
            "TRANSLATION_CONNECTION_TEST_FAILED",
            "translation provider connection test failed",
            kind="unavailable",
        ) from exc
    return TranslationSettingsTestResponse(
        provider=provider.identity.provider,
        model_name=(
            "阿里云机器翻译通用版"
            if request.provider == "aliyun-alimt"
            else (
                "DeepLX"
                if request.provider == "deeplx"
                else request.model_name.strip()
            )
        ),
        latency_ms=latency_ms,
        translated_text=translated,
    )
