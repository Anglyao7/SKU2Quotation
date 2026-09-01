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
    CustomerSubaccountOrderDetail,
    CustomerSubaccountOrderPage,
    CustomerSubaccountPasswordReset,
    CustomerSubaccountStatusUpdate,
    CustomerSubaccountSummary,
    SubaccountPricingPage,
    SubaccountCategoryPriceOverrideRequest,
    SubaccountPricingPolicyResponse,
    SubaccountPricingPolicyUpdate,
    SubaccountProductPriceOverrideRequest,
    SubaccountProductPricingItem,
    SubaccountSkuPriceOverrideRequest,
)
from ..database import get_auth_session
from ..domain.errors import ApplicationError
from ..services.auth.dependencies import (
    current_context,
    get_authenticated_session,
)
from ..services.auth.service import AuthError
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
            session,
            identity_session=_identity_write_session(session, identity_session),
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


@router.get(
    "/customer-accounts/orders/{quote_draft_id}",
    response_model=CustomerSubaccountOrderDetail,
)
def customer_account_order_detail(
    quote_draft_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountOrderDetail:
    try:
        return use_cases.get_customer_subaccount_order(
            session,
            context=current_context(session),
            quote_draft_id=quote_draft_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/customer-accounts/{membership_id}",
    response_model=CustomerSubaccountSummary,
)
def customer_account_detail(
    membership_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> CustomerSubaccountSummary:
    try:
        return use_cases.get_customer_subaccount(
            session,
            context=current_context(session),
            membership_id=membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.get(
    "/customer-accounts/{membership_id}/orders",
    response_model=CustomerSubaccountOrderPage,
)
def customer_account_detail_orders(
    membership_id: UUID,
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
            membership_id=membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-accounts/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_customer_account(
    membership_id: UUID,
    session: Session = Depends(get_authenticated_session),
    identity_session: Session = Depends(get_auth_session),
) -> None:
    try:
        use_cases.delete_customer_subaccount(
            _identity_write_session(session, identity_session),
            context=current_context(session),
            membership_id=membership_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/customer-accounts/{membership_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reset_customer_account_password(
    membership_id: UUID,
    request: CustomerSubaccountPasswordReset,
    session: Session = Depends(get_authenticated_session),
    identity_session: Session = Depends(get_auth_session),
) -> None:
    try:
        use_cases.reset_customer_subaccount_password(
            _identity_write_session(session, identity_session),
            context=current_context(session),
            membership_id=membership_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc
    except AuthError as exc:
        raise application_http_error(
            ApplicationError(exc.code, exc.message, kind="unavailable")
        ) from exc


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


@router.get(
    "/customer-accounts/{membership_id}/pricing",
    response_model=SubaccountPricingPage,
)
def customer_account_pricing(
    membership_id: UUID,
    query: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_authenticated_session),
) -> SubaccountPricingPage:
    try:
        return use_cases.get_subaccount_pricing(
            session,
            context=current_context(session),
            membership_id=membership_id,
            query=query,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.patch(
    "/customer-accounts/{membership_id}/pricing",
    response_model=SubaccountPricingPolicyResponse,
)
def update_customer_account_pricing(
    membership_id: UUID,
    request: SubaccountPricingPolicyUpdate,
    session: Session = Depends(get_authenticated_session),
) -> SubaccountPricingPolicyResponse:
    try:
        return use_cases.update_subaccount_pricing_policy(
            session,
            context=current_context(session),
            membership_id=membership_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/customer-accounts/{membership_id}/pricing/products/{product_id}",
    response_model=SubaccountProductPricingItem,
)
def set_customer_account_product_pricing(
    membership_id: UUID,
    product_id: UUID,
    request: SubaccountProductPriceOverrideRequest,
    session: Session = Depends(get_authenticated_session),
) -> SubaccountProductPricingItem:
    try:
        return use_cases.set_subaccount_product_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            product_id=product_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-accounts/{membership_id}/pricing/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_customer_account_product_pricing(
    membership_id: UUID,
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    try:
        use_cases.clear_subaccount_product_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/customer-accounts/{membership_id}/pricing/skus/{sku_id}",
    response_model=SubaccountProductPricingItem,
)
def set_customer_account_sku_pricing(
    membership_id: UUID,
    sku_id: UUID,
    request: SubaccountSkuPriceOverrideRequest,
    session: Session = Depends(get_authenticated_session),
) -> SubaccountProductPricingItem:
    try:
        return use_cases.set_subaccount_sku_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            sku_id=sku_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-accounts/{membership_id}/pricing/skus/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_customer_account_sku_pricing(
    membership_id: UUID,
    sku_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    try:
        use_cases.clear_subaccount_sku_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            sku_id=sku_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/customer-accounts/{membership_id}/pricing/categories/{category_id}",
    response_model=SubaccountPricingPolicyResponse,
)
def set_customer_account_category_pricing(
    membership_id: UUID,
    category_id: UUID,
    request: SubaccountCategoryPriceOverrideRequest,
    session: Session = Depends(get_authenticated_session),
) -> SubaccountPricingPolicyResponse:
    try:
        return use_cases.update_subaccount_category_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            category_id=category_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-accounts/{membership_id}/pricing/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_customer_account_category_pricing(
    membership_id: UUID,
    category_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    try:
        use_cases.clear_subaccount_category_price_override(
            session,
            context=current_context(session),
            membership_id=membership_id,
            category_id=category_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


def _fixed_self_price(request: SubaccountProductPriceOverrideRequest | SubaccountSkuPriceOverrideRequest) -> None:
    if request.pricing_mode != "FIXED_PRICE":
        raise ApplicationError(
            "CUSTOMER_SELF_PRICE_MODE_INVALID",
            "子账号只能直接设置自己的最终销售价。",
        )


@router.put(
    "/customer-portal/pricing/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def set_customer_portal_product_price(
    product_id: UUID,
    request: SubaccountProductPriceOverrideRequest,
    session: Session = Depends(get_authenticated_session),
) -> None:
    context = current_context(session)
    try:
        _fixed_self_price(request)
        use_cases.set_subaccount_product_price_override(
            session,
            context=context,
            membership_id=context.membership_id,
            product_id=product_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-portal/pricing/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_customer_portal_product_price(
    product_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    context = current_context(session)
    try:
        use_cases.clear_subaccount_product_price_override(
            session,
            context=context,
            membership_id=context.membership_id,
            product_id=product_id,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.put(
    "/customer-portal/pricing/skus/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def set_customer_portal_sku_price(
    sku_id: UUID,
    request: SubaccountSkuPriceOverrideRequest,
    session: Session = Depends(get_authenticated_session),
) -> None:
    context = current_context(session)
    try:
        _fixed_self_price(request)
        use_cases.set_subaccount_sku_price_override(
            session,
            context=context,
            membership_id=context.membership_id,
            sku_id=sku_id,
            request=request,
        )
    except ApplicationError as exc:
        raise application_http_error(exc) from exc


@router.delete(
    "/customer-portal/pricing/skus/{sku_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def clear_customer_portal_sku_price(
    sku_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    context = current_context(session)
    try:
        use_cases.clear_subaccount_sku_price_override(
            session,
            context=context,
            membership_id=context.membership_id,
            sku_id=sku_id,
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
