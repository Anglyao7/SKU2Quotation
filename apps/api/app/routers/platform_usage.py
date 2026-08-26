from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_session
from ..domain.errors import ApplicationError
from ..platform_usage_schemas import PlatformUsageResponse
from ..services.auth.dependencies import RequestContext, require_request_context
from ..use_cases import platform_usage as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/admin", tags=["platform-usage"])
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.get("/usage-analytics", response_model=PlatformUsageResponse)
def platform_usage_endpoint(
    response: Response,
    days: int = Query(default=30, ge=7, le=90),
    context: RequestContext = Depends(require_request_context),
    session: Session = Depends(get_session),
) -> PlatformUsageResponse:
    response.headers.update(NO_STORE_HEADERS)
    try:
        return use_cases.get_platform_usage(session, context=context, days=days)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
