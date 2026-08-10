from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..customer_accounts_schemas import (
    CustomerPortalOrderSummary,
    CustomerPortalOverview,
    CustomerSubaccountAccessUpdate,
    CustomerSubaccountCreate,
    CustomerSubaccountDashboard,
    CustomerSubaccountOrderPage,
    CustomerSubaccountStatusUpdate,
    CustomerSubaccountSummary,
)
from ..database import get_auth_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import (
    current_context,
    get_authenticated_session,
)
from ..use_cases import customer_accounts as use_cases
from .errors import application_http_error


router = APIRouter(prefix="/api/v1", tags=["customer-subaccounts"])


def _identity_write_session(
    session: Session,
    identity_session: Session,
) -> Session:
    """Avoid a second SQLite transaction while an authenticated request is open.

    Production may use a dedicated privileged identity connection. Local SQLite
    has no RLS and uses the request transaction safely, which prevents a reader
    transaction from blocking its own credential write.
    """

    if session.bind is not None and session.bind.dialect.name == "sqlite":
        return session
    return identity_session


@router.get("/customer-accounts", response_model=CustomerSubaccountDashboard)
def customer_accounts_dashboard(
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountDashboard:
    try:
        return use_cases.get_customer_subaccount_dashboard(
            session,
            context=current_context(session),
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.post(
    "/customer-accounts",
    response_model=CustomerSubaccountSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_account(
    request: CustomerSubaccountCreate,
    session: Session = Depends(get_authenticated_session),
    identity_session: Session = Depends(get_auth_session),
) -> CustomerSubaccountSummary:
    try:
        return use_cases.create_customer_subaccount(
            _identity_write_session(session, identity_session),
            context=current_context(session),
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/customer-accounts/orders",
    response_model=CustomerSubaccountOrderPage,
)
def customer_account_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountOrderPage:
    try:
        return use_cases.list_customer_subaccount_orders(
            session,
            context=current_context(session),
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/customer-accounts/{membership_id}/status",
    response_model=CustomerSubaccountSummary,
)
def update_customer_account_status(
    membership_id: UUID,
    request: CustomerSubaccountStatusUpdate,
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountSummary:
    try:
        return use_cases.update_customer_subaccount_status(
            session,
            context=current_context(session),
            membership_id=membership_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/customer-accounts/{membership_id}/access",
    response_model=CustomerSubaccountSummary,
)
def update_customer_account_access(
    membership_id: UUID,
    request: CustomerSubaccountAccessUpdate,
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountSummary:
    try:
        return use_cases.update_customer_subaccount_access(
            session,
            context=current_context(session),
            membership_id=membership_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/customer-portal/overview", response_model=CustomerPortalOverview)
def customer_portal_overview(
    session: Session = Depends(get_authenticated_session),
) -> CustomerPortalOverview:
    try:
        return use_cases.get_customer_portal_overview(
            session,
            context=current_context(session),
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get("/customer-portal/orders", response_model=list[CustomerPortalOrderSummary])
def customer_portal_orders(
    session: Session = Depends(get_authenticated_session),
) -> list[CustomerPortalOrderSummary]:
    try:
        return use_cases.list_customer_portal_orders(
            session,
            context=current_context(session),
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
