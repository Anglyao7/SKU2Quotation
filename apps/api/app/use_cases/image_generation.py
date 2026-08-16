from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..image_generation_schemas import (
    ImageGenerationSettingsResponse,
    ImageGenerationSettingsUpdateRequest,
)
from ..services.auth.dependencies import RequestContext
from ..services.image_generation_configuration import (
    ImageGenerationConfigurationError,
    image_generation_configuration_snapshot,
    save_managed_image_generation_settings,
)


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


def _response(session: Session) -> ImageGenerationSettingsResponse:
    snapshot = image_generation_configuration_snapshot(session)
    return ImageGenerationSettingsResponse(**asdict(snapshot))


def get_settings(
    session: Session,
    *,
    context: RequestContext,
) -> ImageGenerationSettingsResponse:
    _require_platform_admin(context)
    try:
        return _response(session)
    except (ValueError, ImageGenerationConfigurationError) as exc:
        raise ApplicationError(
            "IMAGE_GENERATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: ImageGenerationSettingsUpdateRequest,
) -> ImageGenerationSettingsResponse:
    _require_platform_admin(context)
    try:
        save_managed_image_generation_settings(
            session,
            enabled=request.enabled,
            base_url=request.base_url,
            model_name=request.model_name,
            timeout_seconds=request.timeout_seconds,
            requests_per_minute=request.requests_per_minute,
            concurrency_limit=request.concurrency_limit,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            updated_by_user_id=context.user_id,
        )
        session.commit()
        return _response(session)
    except (ValueError, ImageGenerationConfigurationError) as exc:
        session.rollback()
        raise ApplicationError(
            "IMAGE_GENERATION_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
