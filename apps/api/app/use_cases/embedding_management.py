from dataclasses import asdict

from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..knowledge_embedding_schemas import (
    EmbeddingSettingsResponse,
    EmbeddingSettingsUpdateRequest,
)
from ..services.auth.dependencies import RequestContext
from ..services.embedding import EmbeddingProviderError
from ..services.embedding_configuration import (
    embedding_configuration_snapshot,
    save_managed_embedding_settings,
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
) -> EmbeddingSettingsResponse:
    _require_platform_admin(context)
    try:
        snapshot = embedding_configuration_snapshot(session)
    except (ValueError, EmbeddingProviderError) as exc:
        raise ApplicationError(
            "EMBEDDING_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    return EmbeddingSettingsResponse(**asdict(snapshot))


def update_settings(
    session: Session,
    *,
    context: RequestContext,
    request: EmbeddingSettingsUpdateRequest,
) -> EmbeddingSettingsResponse:
    _require_platform_admin(context)
    try:
        save_managed_embedding_settings(
            session,
            base_url=request.base_url,
            model_name=request.model_name,
            dimensions=request.dimensions,
            timeout_seconds=request.timeout_seconds,
            max_retry_count=request.max_retry_count,
            api_key=(
                request.api_key.get_secret_value()
                if request.api_key is not None
                else None
            ),
            updated_by_user_id=context.user_id,
        )
        session.commit()
        snapshot = embedding_configuration_snapshot(session)
    except (ValueError, EmbeddingProviderError) as exc:
        session.rollback()
        raise ApplicationError(
            "EMBEDDING_CONFIGURATION_INVALID",
            str(exc),
        ) from exc
    return EmbeddingSettingsResponse(**asdict(snapshot))
