from __future__ import annotations

from sqlalchemy.orm import Session

from ..auth_schemas import UserPreferencesResponse, UserPreferencesUpdate
from ..domain.errors import ApplicationError
from ..identity_models import UserRow
from ..services.auth.dependencies import RequestContext


def update_user_preferences(
    session: Session,
    *,
    context: RequestContext,
    request: UserPreferencesUpdate,
) -> UserPreferencesResponse:
    user = session.get(UserRow, context.user_id)
    if user is None or user.deleted_at is not None:
        raise ApplicationError(
            "USER_NOT_FOUND",
            "The current user is no longer available.",
            kind="not_found",
        )
    user.locale = request.locale
    session.commit()
    return UserPreferencesResponse(locale=user.locale)
