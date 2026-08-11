from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..services.auth.dependencies import current_context, get_authenticated_session
from ..use_cases import workspace as use_cases
from ..workspace_schemas import (
    DashboardResponse,
    SupplierCreateRequest,
    SupplierProfileDetail,
    SupplierProfileSummary,
    SupplyChainCreateRequest,
    SupplyChainPageResponse,
    SupplyChainUpdateRequest,
)
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["workspaces"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    import_limit: int = Query(default=6, ge=0, le=20),
    session: Session = Depends(get_authenticated_session),
) -> DashboardResponse:
    context = current_context(session)
    try:
        return use_cases.get_dashboard(
            session,
            tenant_id=context.tenant_id,
            membership_id=context.membership_id,
            permissions=context.permissions,
            import_limit=import_limit,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/supplier-profiles", response_model=list[SupplierProfileSummary])
def list_supplier_profiles(session: Session = Depends(get_authenticated_session)) -> list[SupplierProfileSummary]:
    context = current_context(session)
    try:
        return use_cases.list_suppliers(session, tenant_id=context.tenant_id, permissions=context.permissions)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/supplier-profiles",
    response_model=SupplierProfileSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier_profile(
    request: SupplierCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SupplierProfileSummary:
    context = current_context(session)
    try:
        return use_cases.create_supplier(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/supplier-profiles/{supplier_id}", response_model=SupplierProfileDetail)
def get_supplier_profile(supplier_id: str, session: Session = Depends(get_authenticated_session)) -> SupplierProfileDetail:
    context = current_context(session)
    try:
        return use_cases.get_supplier(session, tenant_id=context.tenant_id, permissions=context.permissions, supplier_id=supplier_id)
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/supply-chain", response_model=SupplyChainPageResponse)
def list_supply_chain_partners(
    query: str | None = Query(default=None, max_length=200),
    partner_status: Literal["ACTIVE", "INACTIVE", "BLOCKED"] | None = Query(
        default=None,
        alias="status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=10, le=100),
    session: Session = Depends(get_authenticated_session),
) -> SupplyChainPageResponse:
    context = current_context(session)
    try:
        return use_cases.list_supply_chain_partners(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            query=query,
            status=partner_status,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/supply-chain",
    response_model=SupplierProfileSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_supply_chain_partner(
    request: SupplyChainCreateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SupplierProfileSummary:
    context = current_context(session)
    try:
        return use_cases.create_supply_chain_partner(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/supply-chain/{supplier_id}",
    response_model=SupplierProfileSummary,
)
def update_supply_chain_partner(
    supplier_id: str,
    request: SupplyChainUpdateRequest,
    session: Session = Depends(get_authenticated_session),
) -> SupplierProfileSummary:
    context = current_context(session)
    try:
        return use_cases.update_supply_chain_partner(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            supplier_id=supplier_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/supply-chain/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_supply_chain_partner(
    supplier_id: str,
    session: Session = Depends(get_authenticated_session),
) -> None:
    context = current_context(session)
    try:
        use_cases.delete_supply_chain_partner(
            session,
            tenant_id=context.tenant_id,
            permissions=context.permissions,
            supplier_id=supplier_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
