from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..trade_flow_schemas import CandidateSelectRequest, CustomerCreateRequest, CustomerResponse, InquiryCreateRequest, InquiryItemConfirmRequest, InquiryItemResponse, InquiryMatchResponse, InquiryResponse, MatchResultResponse, QuotationCreateRequest, QuotationDecisionRequest, QuotationResponse, QuotationRevisionRequest, QuotationSummary
from ..use_cases import trade_flow as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["trade-flow"])


def _ctx(session: Session): return current_context(session)


@router.post("/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(request: CustomerCreateRequest, session: Session = Depends(get_authenticated_session)) -> CustomerResponse:
    context = _ctx(session)
    try: return use_cases.create_customer(session, tenant_id=context.tenant_id, permissions=context.permissions, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/inquiries", response_model=InquiryResponse, status_code=status.HTTP_201_CREATED)
def create_inquiry(request: InquiryCreateRequest, session: Session = Depends(get_authenticated_session)) -> InquiryResponse:
    context = _ctx(session)
    try: return use_cases.create_inquiry(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.get("/inquiries/{inquiry_id}", response_model=InquiryResponse)
def get_inquiry(inquiry_id: UUID, session: Session = Depends(get_authenticated_session)) -> InquiryResponse:
    context = _ctx(session)
    try: return use_cases.get_inquiry(session, tenant_id=context.tenant_id, permissions=context.permissions, inquiry_id=inquiry_id)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.patch("/inquiry-items/{item_id}/confirm", response_model=InquiryItemResponse)
def confirm_item(item_id: UUID, request: InquiryItemConfirmRequest, session: Session = Depends(get_authenticated_session)) -> InquiryItemResponse:
    context = _ctx(session)
    try: return use_cases.confirm_item(session, tenant_id=context.tenant_id, permissions=context.permissions, item_id=item_id, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/inquiries/{inquiry_id}/match", response_model=InquiryMatchResponse)
def match_inquiry(inquiry_id: UUID, limit: int = Query(default=5, ge=1, le=10), session: Session = Depends(get_authenticated_session)) -> InquiryMatchResponse:
    context = _ctx(session)
    try: return use_cases.match_inquiry(session, tenant_id=context.tenant_id, permissions=context.permissions, inquiry_id=inquiry_id, limit=limit)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/inquiry-items/{item_id}/selection", response_model=MatchResultResponse)
def select_candidate(item_id: UUID, request: CandidateSelectRequest, session: Session = Depends(get_authenticated_session)) -> MatchResultResponse:
    context = _ctx(session)
    try: return use_cases.select_candidate(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, item_id=item_id, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/inquiries/{inquiry_id}/quotation", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
def create_quotation(inquiry_id: UUID, request: QuotationCreateRequest, session: Session = Depends(get_authenticated_session)) -> QuotationResponse:
    context = _ctx(session)
    try: return use_cases.create_quotation(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, inquiry_id=inquiry_id, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.get("/quotations/{quotation_id}", response_model=QuotationResponse)
def get_quotation(quotation_id: UUID, session: Session = Depends(get_authenticated_session)) -> QuotationResponse:
    context = _ctx(session)
    try: return use_cases.get_quotation(session, tenant_id=context.tenant_id, permissions=context.permissions, quotation_id=quotation_id)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.get("/quotations", response_model=list[QuotationSummary])
def list_quotations(limit: int = Query(default=100, ge=1, le=500), session: Session = Depends(get_authenticated_session)) -> list[QuotationSummary]:
    context = _ctx(session)
    try: return use_cases.list_quotations(session, tenant_id=context.tenant_id, permissions=context.permissions, limit=limit)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/quotations/{quotation_id}/decision", response_model=QuotationResponse)
def decide_quotation(quotation_id: UUID, request: QuotationDecisionRequest, session: Session = Depends(get_authenticated_session)) -> QuotationResponse:
    context = _ctx(session)
    try: return use_cases.decide_quotation(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, quotation_id=quotation_id, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc


@router.post("/quotations/{quotation_id}/revisions", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
def revise_quotation(quotation_id: UUID, request: QuotationRevisionRequest, session: Session = Depends(get_authenticated_session)) -> QuotationResponse:
    context = _ctx(session)
    try: return use_cases.revise_quotation(session, tenant_id=context.tenant_id, membership_id=context.membership_id, permissions=context.permissions, quotation_id=quotation_id, request=request)
    except ApplicationError as exc: raise application_http_error(exc) from exc
