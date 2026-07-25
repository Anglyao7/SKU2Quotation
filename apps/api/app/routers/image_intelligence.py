from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..image_intelligence_schemas import ImageProjectionResponse, ImageSearchResponse
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..services.rate_limit import configured_limit, enforce_rate_limit
from ..use_cases import image_intelligence as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["image-intelligence"])


@router.post("/product-images/{image_id}/intelligence", response_model=ImageProjectionResponse)
def project_product_image(
    image_id: UUID,
    request: Request,
    session: Session = Depends(get_authenticated_session),
) -> ImageProjectionResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-image-project",
        limit=configured_limit("RATE_LIMIT_AI_IMAGE_PROJECT_REQUESTS", 20),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_IMAGE_PROJECT_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    try:
        return use_cases.project_product_image(session, tenant_id=context.tenant_id, permissions=context.permissions, image_id=image_id)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc

@router.post("/image-searches", response_model=ImageSearchResponse)
async def image_search(
    request: Request,
    file: UploadFile = File(...),
    limit: int = Query(default=10, ge=1, le=25),
    session: Session = Depends(get_authenticated_session),
) -> ImageSearchResponse:
    context = current_context(session)
    enforce_rate_limit(
        request,
        scope="ai-image-search",
        limit=configured_limit("RATE_LIMIT_AI_IMAGE_SEARCH_REQUESTS", 10),
        window_seconds=configured_limit(
            "RATE_LIMIT_AI_IMAGE_SEARCH_WINDOW_SECONDS", 60, maximum=86_400
        ),
        token=request.headers.get("authorization"),
    )
    content = await file.read(int(__import__("os").getenv("IMAGE_SEARCH_MAX_BYTES", str(20 * 1024 * 1024))) + 1)
    await file.close()
    try:
        return use_cases.search_by_image(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, filename=file.filename or "query.img", declared_content_type=file.content_type or "application/octet-stream", content=content, limit=limit)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
