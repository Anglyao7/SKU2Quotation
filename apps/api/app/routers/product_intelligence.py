from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..models import (
    ProductCandidateApproveRequest,
    ProductCandidateApproveResponse,
    ProductCandidateRejectRequest,
    ProductCandidateRejectResponse,
    ProductFieldCandidate,
)
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import product_intelligence as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1/ai/product-intelligence", tags=["product-intelligence"])


@router.get(
    "/tasks/{task_id}/candidates",
    response_model=list[ProductFieldCandidate],
)
def list_product_field_candidates(
    task_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> list[ProductFieldCandidate]:
    return use_cases.list_candidates(
        session,
        tenant_id=current_context(session).tenant_id,
        task_id=task_id,
    )


@router.post(
    "/tasks/{task_id}/groups/{candidate_group_key}/approve",
    response_model=ProductCandidateApproveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def approve_product_candidate_group(
    task_id: UUID,
    candidate_group_key: str,
    request: ProductCandidateApproveRequest,
    session: Session = Depends(get_authenticated_session),
) -> ProductCandidateApproveResponse:
    context = current_context(session)
    try:
        return use_cases.approve_candidate(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            task_id=task_id,
            candidate_group_key=candidate_group_key,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/tasks/{task_id}/groups/{candidate_group_key}/reject",
    response_model=ProductCandidateRejectResponse,
)
def reject_product_candidate_group(
    task_id: UUID,
    candidate_group_key: str,
    request: ProductCandidateRejectRequest,
    session: Session = Depends(get_authenticated_session),
) -> ProductCandidateRejectResponse:
    context = current_context(session)
    try:
        return use_cases.reject_candidate(
            session,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            task_id=task_id,
            candidate_group_key=candidate_group_key,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
