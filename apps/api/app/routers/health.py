from typing import Any

from fastapi import APIRouter, Depends, Response, status

from ..database import get_session
from ..use_cases.system_health import liveness_payload, readiness_payload

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
@router.get("/health/live")
def health() -> dict[str, Any]:
    """Process liveness; deliberately does not call external dependencies."""
    return liveness_payload()


@router.get("/health/ready")
def readiness(
    response: Response,
    session: Any = Depends(get_session),
) -> dict[str, Any]:
    ready, payload = readiness_payload(session)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
