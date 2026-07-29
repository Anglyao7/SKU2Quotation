from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..system_schemas import OutboxMetricsResponse, SystemMonitoringResponse
from ..use_cases import system_operations
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/metrics", response_model=SystemMonitoringResponse)
def system_metrics(
    response: Response,
    session: Session = Depends(get_authenticated_session),
) -> SystemMonitoringResponse:
    context = current_context(session)
    response.headers["Cache-Control"] = "no-store"
    try:
        return system_operations.get_system_monitoring(context=context)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/outbox/metrics", response_model=OutboxMetricsResponse)
def outbox_metrics(
    session: Session = Depends(get_authenticated_session),
) -> OutboxMetricsResponse:
    context = current_context(session)
    try:
        return system_operations.get_outbox_metrics(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
