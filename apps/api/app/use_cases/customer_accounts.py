from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..customer_accounts_schemas import (
    CUSTOMER_SUBACCOUNT_CAPABILITIES,
    CUSTOMER_SUBACCOUNT_MODULES,
    CustomerPortalOrderSummary,
    CustomerPortalOverview,
    CustomerSubaccountAccessUpdate,
    CustomerSubaccountCreate,
    CustomerSubaccountDashboard,
    CustomerSubaccountOrderDetail,
    CustomerSubaccountOrderItemSummary,
    CustomerSubaccountOrderPage,
    CustomerSubaccountOrderSummary,
    CustomerSubaccountPasswordReset,
    CustomerSubaccountStatusUpdate,
    CustomerSubaccountSummary,
    normalize_capabilities,
    normalize_modules,
    SubaccountPricingPage,
    SubaccountPricingPolicyResponse,
    SubaccountPricingPolicyUpdate,
    SubaccountCategoryPriceOverrideRequest,
    SubaccountProductPriceOverrideRequest,
    SubaccountProductPricingItem,
    SubaccountSkuPriceOverrideRequest,
    SubaccountSkuPricingItem,
)
from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import (
    CustomerAccountAccessEventRow,
    LocalAccountCredentialRow,
    MembershipRoleRow,
    MembershipRow,
    PermissionRow,
    TenantRow,
    UserRow,
)
from ..model_mixins import utcnow
from ..public_catalog_models import (
    PublicCatalogOfferRow,
    PublicQuoteDraftRow,
    PublicQuoteDraftItemRow,
    StorefrontOrderRecordRow,
)
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductCategoryRow, ProductRow
from ..subaccount_pricing_models import (
    SubaccountCategoryPriceOverrideRow,
    SubaccountPricingPolicyRow,
    SubaccountProductPriceOverrideRow,
    SubaccountSkuPriceOverrideRow,
)
from ..saas_seed import ensure_tenant_rbac
from ..services.auth.dependencies import RequestContext
from ..services.auth.local_credentials import normalize_local_identifier
from ..services.auth.password_accounts import (
    PasswordIdentityProvisioningError,
    password_is_valid,
    provision_password_identity,
)
from ..services.auth.service import AuthError, reset_password_for_user
from ..services.subaccount_pricing import (
    effective_subaccount_price,
    subaccount_category_price_rules,
    subaccount_sku_price_rules,
)
from ..services.rbac import (
    CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES,
    PLATFORM_ADMIN_ONLY_PERMISSION_CODES,
)


_CUSTOMER_SCOPE = "CUSTOMER_SUBACCOUNT"
_PORTAL_ROLE = "CUSTOMER_SUBACCOUNT"
_CAPABILITY_PERMISSIONS = {
    "catalog": "customer_portal.access",
    "submit_orders": "customer_portal.order_create",
    "view_orders": "customer_portal.order_view_self",
}

# Parent-selected module scopes are translated to the existing fine-grained
# permission catalogue.  The mapping deliberately excludes owner-only modules;
# even if a caller sends a crafted permission list, rbac.py removes those
# permissions for customer subaccounts.
_SUBACCOUNT_MODULE_PERMISSION_MODULES = {
    "products": frozenset({"product", "catalog"}),
    "inquiries": frozenset({"customer", "inquiry"}),
    "quotations": frozenset({"quotation", "order"}),
    "announcements": frozenset({"announcement"}),
    "support": frozenset({"support"}),
}


def _modules_from_permissions(value: object) -> list[str]:
    """Project an account-level permission ceiling back to UI module names.

    Existing child rows use either NULL or the former three portal permissions;
    both represent the old all-access operator default.  New rows contain the
    concrete safe permission codes generated from the module selector.
    """

    if not isinstance(value, list):
        return list(CUSTOMER_SUBACCOUNT_MODULES)
    permissions = {str(code) for code in value}
    if not permissions or permissions == {
        "customer_portal.access",
        "customer_portal.order_create",
        "customer_portal.order_view_self",
    }:
        return ["products"] if not permissions else list(CUSTOMER_SUBACCOUNT_MODULES)
    selected: set[str] = set()
    for code in permissions:
        if code.startswith(("product.", "catalog.")) or code == "customer_portal.access":
            selected.add("products")
        elif code.startswith(("customer.", "inquiry.")) or code in {
            "customer_portal.order_create",
            "customer_portal.order_view_self",
        }:
            selected.add("inquiries")
        elif code.startswith(("quotation.", "order.")):
            selected.add("quotations")
        elif code.startswith("announcement."):
            selected.add("announcements")
        elif code.startswith("support.") and not code.startswith("support.ai."):
            selected.add("support")
    return normalize_modules(list(selected))


def _capabilities_from_permissions(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(CUSTOMER_SUBACCOUNT_CAPABILITIES)
    permissions = {str(code) for code in value}
    return normalize_capabilities(
        [
            capability
            for capability, permission in _CAPABILITY_PERMISSIONS.items()
            if permission in permissions
        ]
    )


def _permissions_from_capabilities(value: list[str]) -> list[str]:
    selected = set(value)
    return [
        permission
        for capability, permission in _CAPABILITY_PERMISSIONS.items()
        if capability in selected
    ]


def _permissions_from_modules(
    session: Session,
    value: list[str],
) -> list[str]:
    """Return concrete safe permission codes for a selected module scope."""

    modules = normalize_modules(value)
    allowed_permission_modules = frozenset(
        permission_module
        for module in modules
        for permission_module in _SUBACCOUNT_MODULE_PERMISSION_MODULES.get(module, ())
    )
    portal_actions = set()
    if "products" in modules:
        portal_actions.add("customer_portal.access")
    if "inquiries" in modules:
        portal_actions.update(
            {"customer_portal.order_create", "customer_portal.order_view_self"}
        )
    rows = session.scalars(
        select(PermissionRow).where(PermissionRow.deleted_at.is_(None))
    ).all()
    selected = {
        row.code
        for row in rows
        if row.module in allowed_permission_modules
        and row.code not in CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES
        and row.code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
    }
    selected.update(
        row.code
        for row in rows
        if row.code in portal_actions
        and row.code not in CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES
        and row.code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
    )
    return sorted(selected)


def _permissions_for_subaccount_request(
    session: Session,
    *,
    modules: list[str] | None,
    capabilities: list[str] | None,
) -> list[str]:
    if modules is not None:
        return _permissions_from_modules(session, modules)
    return _permissions_from_capabilities(
        capabilities or list(CUSTOMER_SUBACCOUNT_CAPABILITIES)
    )


def _require_parent(context: RequestContext) -> None:
    if context.account_scope != "STAFF" or "customer_portal.subaccount_manage" not in context.permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            "Customer subaccount management permission is required.",
            kind="forbidden",
        )


def _require_customer_portal(
    context: RequestContext,
    permission: str = "customer_portal.access",
) -> None:
    if (
        context.account_scope != _CUSTOMER_SCOPE
        or permission not in context.permissions
    ):
        raise ApplicationError(
            "CUSTOMER_PORTAL_ACCESS_DENIED",
            "This account can only access the customer portal.",
            kind="forbidden",
        )


def _subaccount_metrics(
    session: Session,
    *,
    tenant_id: UUID,
    membership_ids: list[UUID],
) -> tuple[
    dict[UUID, tuple[int, object | None]],
    dict[UUID, tuple[int, object | None]],
    dict[UUID, Decimal],
    dict[UUID, tuple[int, Decimal]],
    dict[UUID, tuple[int, Decimal]],
]:
    if not membership_ids:
        return {}, {}, {}, {}, {}
    since = utcnow() - timedelta(days=30)
    access_rows = session.execute(
        select(
            CustomerAccountAccessEventRow.membership_id,
            func.count(CustomerAccountAccessEventRow.id).filter(
                CustomerAccountAccessEventRow.event_type == "LOGIN",
                CustomerAccountAccessEventRow.occurred_at >= since,
            ),
            func.max(
                case(
                    (CustomerAccountAccessEventRow.event_type == "LOGIN", CustomerAccountAccessEventRow.occurred_at),
                    else_=None,
                )
            ),
        )
        .where(
            CustomerAccountAccessEventRow.tenant_id == tenant_id,
            CustomerAccountAccessEventRow.membership_id.in_(membership_ids),
        )
        .group_by(CustomerAccountAccessEventRow.membership_id)
    ).all()
    order_rows = session.execute(
        select(
            PublicQuoteDraftRow.submitted_by_membership_id,
            func.count(PublicQuoteDraftRow.id),
            func.max(PublicQuoteDraftRow.created_at),
            func.coalesce(func.sum(PublicQuoteDraftRow.estimated_total), 0),
        )
        .where(
            PublicQuoteDraftRow.tenant_id == tenant_id,
            PublicQuoteDraftRow.submitted_by_membership_id.in_(membership_ids),
        )
        .group_by(PublicQuoteDraftRow.submitted_by_membership_id)
    ).all()
    timezone_name = session.scalar(
        select(TenantRow.timezone).where(TenantRow.id == tenant_id)
    ) or "UTC"
    try:
        reporting_zone = ZoneInfo(str(timezone_name))
    except ZoneInfoNotFoundError:
        reporting_zone = ZoneInfo("UTC")
    local_now = utcnow().astimezone(reporting_zone)
    today_start = datetime.combine(local_now.date(), time.min, tzinfo=reporting_zone)
    today_end = today_start + timedelta(days=1)
    month_start = datetime(local_now.year, local_now.month, 1, tzinfo=reporting_zone)
    month_end = (
        datetime(local_now.year + 1, 1, 1, tzinfo=reporting_zone)
        if local_now.month == 12
        else datetime(local_now.year, local_now.month + 1, 1, tzinfo=reporting_zone)
    )
    confirmed_status = StorefrontOrderRecordRow.status.in_(("CONFIRMED", "COMPLETED"))
    sales_rows = session.execute(
        select(
            StorefrontOrderRecordRow.submitted_by_membership_id,
            func.count(StorefrontOrderRecordRow.id).filter(
                confirmed_status,
                StorefrontOrderRecordRow.confirmed_at >= month_start,
                StorefrontOrderRecordRow.confirmed_at < month_end,
            ),
            func.coalesce(
                func.sum(StorefrontOrderRecordRow.total_amount).filter(
                    confirmed_status,
                    StorefrontOrderRecordRow.confirmed_at >= month_start,
                    StorefrontOrderRecordRow.confirmed_at < month_end,
                ),
                0,
            ),
            func.count(StorefrontOrderRecordRow.id).filter(
                confirmed_status,
                StorefrontOrderRecordRow.confirmed_at >= today_start,
                StorefrontOrderRecordRow.confirmed_at < today_end,
            ),
            func.coalesce(
                func.sum(StorefrontOrderRecordRow.total_amount).filter(
                    confirmed_status,
                    StorefrontOrderRecordRow.confirmed_at >= today_start,
                    StorefrontOrderRecordRow.confirmed_at < today_end,
                ),
                0,
            ),
        )
        .where(
            StorefrontOrderRecordRow.tenant_id == tenant_id,
            StorefrontOrderRecordRow.submitted_by_membership_id.in_(membership_ids),
            StorefrontOrderRecordRow.deleted_at.is_(None),
        )
        .group_by(StorefrontOrderRecordRow.submitted_by_membership_id)
    ).all()
    return (
        {row[0]: (int(row[1] or 0), row[2]) for row in access_rows},
        {row[0]: (int(row[1] or 0), row[2]) for row in order_rows},
        {row[0]: Decimal(str(row[3] or 0)) for row in order_rows},
        {row[0]: (int(row[1] or 0), Decimal(str(row[2] or 0))) for row in sales_rows},
        {row[0]: (int(row[3] or 0), Decimal(str(row[4] or 0))) for row in sales_rows},
    )


def _pricing_policy(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    create: bool = True,
) -> SubaccountPricingPolicyRow | None:
    policy = session.scalar(
        select(SubaccountPricingPolicyRow).where(
            SubaccountPricingPolicyRow.tenant_id == tenant_id,
            SubaccountPricingPolicyRow.membership_id == membership_id,
            SubaccountPricingPolicyRow.deleted_at.is_(None),
        )
    )
    if policy is None and create:
        policy = SubaccountPricingPolicyRow(
            tenant_id=tenant_id,
            membership_id=membership_id,
            markup_percent=Decimal("0"),
            hidden_product_ids=[],
        )
        session.add(policy)
        session.flush()
    return policy


def _sku_override_count(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
) -> int:
    return int(
        session.scalar(
            select(func.count(SubaccountSkuPriceOverrideRow.id)).where(
                SubaccountSkuPriceOverrideRow.tenant_id == tenant_id,
                SubaccountSkuPriceOverrideRow.membership_id == membership_id,
                SubaccountSkuPriceOverrideRow.is_active.is_(True),
                SubaccountSkuPriceOverrideRow.deleted_at.is_(None),
            )
        )
        or 0
    )


def _parent_child_membership(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
) -> MembershipRow:
    _require_parent(context)
    membership = session.scalar(
        select(MembershipRow).where(
            MembershipRow.id == membership_id,
            MembershipRow.tenant_id == context.tenant_id,
            MembershipRow.parent_membership_id == context.membership_id,
            MembershipRow.account_scope == _CUSTOMER_SCOPE,
            MembershipRow.status.in_(("active", "suspended")),
            MembershipRow.deleted_at.is_(None),
        )
    )
    if membership is None:
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_NOT_FOUND",
            "Customer subaccount was not found.",
            kind="not_found",
        )
    return membership


def _summary_rows(
    session: Session,
    *,
    tenant_id: UUID,
    parent_membership_id: UUID,
) -> list[CustomerSubaccountSummary]:
    rows = list(
        session.execute(
            select(MembershipRow, UserRow)
            .join(UserRow, UserRow.id == MembershipRow.user_id)
            .where(
                MembershipRow.tenant_id == tenant_id,
                MembershipRow.parent_membership_id == parent_membership_id,
                MembershipRow.account_scope == _CUSTOMER_SCOPE,
            )
            .order_by(MembershipRow.created_at.desc(), MembershipRow.id)
        ).all()
    )
    membership_ids = [membership.id for membership, _user in rows]
    access, orders, order_amounts, month_sales, today_sales = _subaccount_metrics(
        session, tenant_id=tenant_id, membership_ids=membership_ids
    )
    policies = {
        row.membership_id: row
        for row in session.scalars(
            select(SubaccountPricingPolicyRow).where(
                SubaccountPricingPolicyRow.tenant_id == tenant_id,
                SubaccountPricingPolicyRow.membership_id.in_(membership_ids),
                SubaccountPricingPolicyRow.deleted_at.is_(None),
            )
        ).all()
    }
    override_counts = {
        membership_id: int(count or 0)
        for membership_id, count in session.execute(
            select(
                SubaccountProductPriceOverrideRow.membership_id,
                func.count(SubaccountProductPriceOverrideRow.id),
            )
            .where(
                SubaccountProductPriceOverrideRow.tenant_id == tenant_id,
                SubaccountProductPriceOverrideRow.membership_id.in_(membership_ids),
                SubaccountProductPriceOverrideRow.is_active.is_(True),
                SubaccountProductPriceOverrideRow.deleted_at.is_(None),
            )
            .group_by(SubaccountProductPriceOverrideRow.membership_id)
        ).all()
    }
    category_override_counts = {
        membership_id: int(count or 0)
        for membership_id, count in session.execute(
            select(
                SubaccountCategoryPriceOverrideRow.membership_id,
                func.count(SubaccountCategoryPriceOverrideRow.id),
            )
            .where(
                SubaccountCategoryPriceOverrideRow.tenant_id == tenant_id,
                SubaccountCategoryPriceOverrideRow.membership_id.in_(membership_ids),
                SubaccountCategoryPriceOverrideRow.is_active.is_(True),
                SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
            )
            .group_by(SubaccountCategoryPriceOverrideRow.membership_id)
        ).all()
    }
    sku_override_counts = {
        membership_id: int(count or 0)
        for membership_id, count in session.execute(
            select(
                SubaccountSkuPriceOverrideRow.membership_id,
                func.count(SubaccountSkuPriceOverrideRow.id),
            )
            .where(
                SubaccountSkuPriceOverrideRow.tenant_id == tenant_id,
                SubaccountSkuPriceOverrideRow.membership_id.in_(membership_ids),
                SubaccountSkuPriceOverrideRow.is_active.is_(True),
                SubaccountSkuPriceOverrideRow.deleted_at.is_(None),
            )
            .group_by(SubaccountSkuPriceOverrideRow.membership_id)
        ).all()
    }
    return [
        CustomerSubaccountSummary(
            id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            login_identifier=membership.login_identifier or user.email_normalized or "—",
            email=user.email_normalized,
            status=membership.status,
            capabilities=_capabilities_from_permissions(
                membership.permission_overrides
            ),
            modules=_modules_from_permissions(membership.permission_overrides),
            created_at=membership.created_at,
            last_login_at=user.last_login_at or access.get(membership.id, (0, None))[1],
            login_count_30d=access.get(membership.id, (0, None))[0],
            order_count=orders.get(membership.id, (0, None))[0],
            last_order_at=orders.get(membership.id, (0, None))[1],
            order_amount=order_amounts.get(membership.id, Decimal("0")),
            today_order_count=today_sales.get(membership.id, (0, Decimal("0")))[0],
            today_order_amount=today_sales.get(membership.id, (0, Decimal("0")))[1],
            month_order_count=month_sales.get(membership.id, (0, Decimal("0")))[0],
            month_order_amount=month_sales.get(membership.id, (0, Decimal("0")))[1],
            markup_percent=(policies.get(membership.id).markup_percent if policies.get(membership.id) else Decimal("0")),
            override_count=override_counts.get(membership.id, 0),
            category_override_count=category_override_counts.get(membership.id, 0),
            sku_override_count=sku_override_counts.get(membership.id, 0),
        )
        for membership, user in rows
    ]


def _order_summary(
    draft: PublicQuoteDraftRow,
    membership: MembershipRow,
    user: UserRow,
) -> CustomerSubaccountOrderSummary:
    return CustomerSubaccountOrderSummary(
        id=draft.id,
        quote_number=draft.request_number,
        status=draft.status,
        submitted_by_membership_id=membership.id,
        submitted_by_name=user.display_name,
        customer_name=draft.customer_name,
        customer_company=draft.customer_company,
        currency=draft.currency,
        total_amount=draft.estimated_total,
        created_at=draft.created_at,
        valid_until=draft.expires_at,
        visitor_country_code=getattr(draft, "visitor_country_code", None),
    )


def _child_order_statement(*, context: RequestContext):
    """Return the immutable order trail belonging to this owner's direct children."""

    return (
        select(PublicQuoteDraftRow, MembershipRow, UserRow)
        .join(
            MembershipRow,
            (MembershipRow.tenant_id == PublicQuoteDraftRow.tenant_id)
            & (MembershipRow.id == PublicQuoteDraftRow.submitted_by_membership_id),
        )
        .join(UserRow, UserRow.id == MembershipRow.user_id)
        .where(
            PublicQuoteDraftRow.tenant_id == context.tenant_id,
            MembershipRow.parent_membership_id == context.membership_id,
            MembershipRow.account_scope == _CUSTOMER_SCOPE,
        )
    )


def get_customer_subaccount_dashboard(
    session: Session,
    *,
    context: RequestContext,
) -> CustomerSubaccountDashboard:
    _require_parent(context)
    accounts = _summary_rows(
        session,
        tenant_id=context.tenant_id,
        parent_membership_id=context.membership_id,
    )
    return CustomerSubaccountDashboard(
        accounts=accounts,
        active_count=sum(row.status == "active" for row in accounts),
        suspended_count=sum(row.status == "suspended" for row in accounts),
        order_count=sum(row.order_count for row in accounts),
        order_amount=sum((row.order_amount for row in accounts), Decimal("0")),
        today_order_count=sum(row.today_order_count for row in accounts),
        today_order_amount=sum((row.today_order_amount for row in accounts), Decimal("0")),
        month_order_count=sum(row.month_order_count for row in accounts),
        month_order_amount=sum((row.month_order_amount for row in accounts), Decimal("0")),
        currency=str(
            session.scalar(
                select(TenantRow.default_currency).where(
                    TenantRow.id == context.tenant_id
                )
            )
            or "CNY"
        ).upper(),
    )


def list_customer_subaccount_orders(
    session: Session,
    *,
    context: RequestContext,
    page: int,
    page_size: int,
) -> CustomerSubaccountOrderPage:
    """List every direct-child order through an owner-scoped read-only pager."""

    _require_parent(context)
    statement = _child_order_statement(context=context)
    total = int(
        session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        )
        or 0
    )
    rows = list(
        session.execute(
            statement.order_by(PublicQuoteDraftRow.created_at.desc(), PublicQuoteDraftRow.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return CustomerSubaccountOrderPage(
        items=[_order_summary(*row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


def get_customer_subaccount_order(
    session: Session,
    *,
    context: RequestContext,
    quote_draft_id: UUID,
) -> CustomerSubaccountOrderDetail:
    """Return a read-only child quote with its selected SKUs and final prices."""

    _require_parent(context)
    row = session.execute(
        _child_order_statement(context=context).where(
            PublicQuoteDraftRow.id == quote_draft_id
        )
    ).one_or_none()
    if row is None:
        raise ApplicationError(
            "CUSTOMER_ORDER_NOT_FOUND",
            "Customer subaccount order was not found.",
            kind="not_found",
        )
    draft, membership, user = row
    items = session.scalars(
        select(PublicQuoteDraftItemRow)
        .where(
            PublicQuoteDraftItemRow.tenant_id == context.tenant_id,
            PublicQuoteDraftItemRow.quote_draft_id == draft.id,
            PublicQuoteDraftItemRow.deleted_at.is_(None),
        )
        .order_by(PublicQuoteDraftItemRow.position, PublicQuoteDraftItemRow.id)
    ).all()
    summary = _order_summary(draft, membership, user)
    return CustomerSubaccountOrderDetail(
        **summary.model_dump(),
        items=[
            CustomerSubaccountOrderItemSummary(
                sku_id=item.sku_id,
                product_id=item.product_id_snapshot,
                sku_code=item.sku_code_snapshot,
                product_name=item.name_snapshot,
                quantity=item.quantity,
                currency=item.currency_snapshot,
                unit_price=item.unit_price_snapshot,
                line_total=item.line_total,
            )
            for item in items
        ],
    )


def create_customer_subaccount(
    identity_session: Session,
    *,
    context: RequestContext,
    request: CustomerSubaccountCreate,
) -> CustomerSubaccountSummary:
    _require_parent(context)
    password = request.password.get_secret_value()
    if not password_is_valid(
        password=password,
        identifier=request.login_identifier,
        display_name=request.display_name,
    ):
        raise ApplicationError(
            "PASSWORD_POLICY_VIOLATION",
            "Password must be exactly 6 digits.",
            kind="invalid",
        )
    set_request_context(
        identity_session,
        organization_id=context.organization_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    existing_membership = identity_session.scalar(
        select(MembershipRow.id).where(
            MembershipRow.tenant_id == context.tenant_id,
            MembershipRow.login_identifier == request.login_identifier.casefold(),
        )
    )
    if existing_membership is not None:
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_IDENTIFIER_CONFLICT",
            "This login account is already in use.",
            kind="conflict",
        )
    roles = ensure_tenant_rbac(identity_session, tenant_id=context.tenant_id)
    portal_role = roles.get(_PORTAL_ROLE)
    if portal_role is None:
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_ROLE_UNAVAILABLE",
            "Customer portal permissions are not available yet.",
            kind="conflict",
        )
    try:
        provisioned = provision_password_identity(
            identity_session,
            identifier=request.login_identifier,
            password=password,
            display_name=request.display_name,
            email=request.email,
            local_identity_provider="local-subaccount",
        )
    except PasswordIdentityProvisioningError as exc:
        if exc.reason == "identifier_conflict":
            raise ApplicationError(
                "CUSTOMER_ACCOUNT_IDENTIFIER_CONFLICT",
                "This login account is already in use.",
                kind="conflict",
            ) from exc
        if exc.reason == "provider_unavailable":
            raise ApplicationError(
                "AUTH_PROVIDER_UNAVAILABLE",
                "The configured identity provider cannot create customer accounts.",
                kind="unavailable",
            ) from exc
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_PROVISIONING_FAILED",
            "The customer account could not be created. Check that the account is unique and try again.",
            kind="conflict",
        ) from exc
    user = provisioned.user
    local_material = provisioned.local_credential
    membership = MembershipRow(
        tenant_id=context.tenant_id,
        user_id=user.id,
        account_scope=_CUSTOMER_SCOPE,
        parent_membership_id=context.membership_id,
        login_identifier=request.login_identifier.casefold(),
        status="active",
        joined_at=utcnow(),
        permission_overrides=_permissions_for_subaccount_request(
            identity_session,
            modules=request.modules,
            capabilities=request.capabilities,
        ),
    )
    identity_session.add(user)
    identity_session.add(membership)
    try:
        identity_session.flush()
        identity_session.add(
            MembershipRoleRow(
                tenant_id=context.tenant_id,
                membership_id=membership.id,
                role_id=portal_role.id,
                assigned_by_user_id=context.user_id,
            )
        )
        if local_material is not None:
            salt, password_hash = local_material
            identity_session.add(
                LocalAccountCredentialRow(
                    user_id=user.id,
                    identifier_normalized=normalize_local_identifier(
                        request.login_identifier
                    ),
                    password_salt=salt,
                    password_hash=password_hash,
                )
            )
        identity_session.commit()
    except IntegrityError as exc:
        identity_session.rollback()
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_IDENTIFIER_CONFLICT",
            "This login account is already in use.",
            kind="conflict",
        ) from exc
    summaries = _summary_rows(
        identity_session,
        tenant_id=context.tenant_id,
        parent_membership_id=context.membership_id,
    )
    return next(summary for summary in summaries if summary.id == membership.id)


def reset_customer_subaccount_password(
    identity_session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    request: CustomerSubaccountPasswordReset,
) -> None:
    """Issue a new password and revoke every existing child session."""

    child = _parent_child_membership(
        identity_session,
        context=context,
        membership_id=membership_id,
    )
    set_request_context(
        identity_session,
        organization_id=context.organization_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    password = request.password.get_secret_value()
    if not password_is_valid(
        password=password,
        identifier=child.login_identifier or "",
        display_name="",
    ):
        raise ApplicationError(
            "PASSWORD_POLICY_VIOLATION",
            "Password must be exactly 6 digits.",
            kind="invalid",
        )
    try:
        reset_password_for_user(
            identity_session,
            user_id=child.user_id,
            new_password=password,
        )
    except AuthError as exc:
        kind = (
            "invalid"
            if exc.status_code == 422
            else "not_found"
            if exc.status_code == 404
            else "unavailable"
            if exc.status_code >= 500
            else "conflict"
        )
        raise ApplicationError(exc.code, exc.message, kind=kind) from exc


def update_customer_subaccount_status(
    identity_session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    request: CustomerSubaccountStatusUpdate,
) -> CustomerSubaccountSummary:
    _require_parent(context)
    set_request_context(
        identity_session,
        organization_id=context.organization_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    membership = identity_session.scalar(
        select(MembershipRow).where(
            MembershipRow.id == membership_id,
            MembershipRow.tenant_id == context.tenant_id,
            MembershipRow.parent_membership_id == context.membership_id,
            MembershipRow.account_scope == _CUSTOMER_SCOPE,
        )
    )
    if membership is None:
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_NOT_FOUND",
            "Customer subaccount was not found.",
            kind="not_found",
        )
    membership.status = request.status
    membership.permission_version += 1
    identity_session.commit()
    summaries = _summary_rows(
        identity_session,
        tenant_id=context.tenant_id,
        parent_membership_id=context.membership_id,
    )
    return next(summary for summary in summaries if summary.id == membership_id)


def update_customer_subaccount_access(
    identity_session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    request: CustomerSubaccountAccessUpdate,
) -> CustomerSubaccountSummary:
    _require_parent(context)
    set_request_context(
        identity_session,
        organization_id=context.organization_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
    )
    membership = identity_session.scalar(
        select(MembershipRow).where(
            MembershipRow.id == membership_id,
            MembershipRow.tenant_id == context.tenant_id,
            MembershipRow.parent_membership_id == context.membership_id,
            MembershipRow.account_scope == _CUSTOMER_SCOPE,
        )
    )
    if membership is None:
        raise ApplicationError(
            "CUSTOMER_ACCOUNT_NOT_FOUND",
            "Customer subaccount was not found.",
            kind="not_found",
        )
    next_permissions = _permissions_for_subaccount_request(
        identity_session,
        modules=request.modules,
        capabilities=request.capabilities,
    )
    if membership.permission_overrides != next_permissions:
        membership.permission_overrides = next_permissions
        membership.permission_version += 1
    identity_session.commit()
    summaries = _summary_rows(
        identity_session,
        tenant_id=context.tenant_id,
        parent_membership_id=context.membership_id,
    )
    return next(summary for summary in summaries if summary.id == membership_id)


def _pricing_product_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    page: int,
    page_size: int,
):
    normalized = query.strip().casefold()
    base = (
        select(ProductRow, PublicCatalogOfferRow, SkuRow, ProductCategoryRow)
        .join(
            SkuRow,
            (SkuRow.tenant_id == ProductRow.tenant_id)
            & (SkuRow.product_id == ProductRow.id),
        )
        .join(
            PublicCatalogOfferRow,
            (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
            & (PublicCatalogOfferRow.sku_id == SkuRow.id),
        )
        .outerjoin(
            ProductCategoryRow,
            (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
            & (ProductCategoryRow.id == ProductRow.category_id)
            & (ProductCategoryRow.deleted_at.is_(None)),
        )
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
            SkuRow.status == "ACTIVE",
            SkuRow.deleted_at.is_(None),
            PublicCatalogOfferRow.publication_status == "PUBLISHED",
            PublicCatalogOfferRow.deleted_at.is_(None),
        )
    )
    if normalized:
        pattern = f"%{normalized}%"
        base = base.where(
            or_(
                func.lower(ProductRow.name).like(pattern),
                func.lower(func.coalesce(ProductRow.product_code, "")).like(pattern),
                func.lower(SkuRow.sku_code).like(pattern),
            )
        )
    # Page by product ids first, then load all published SKUs for those
    # products. Paging the joined SKU rows directly would under-fill a page
    # whenever one product has many variants. The second query intentionally
    # drops the search predicate: a search hit selects a product, and the
    # pricing editor must still show that product's complete SKU price range.
    product_ids_statement = (
        base.with_only_columns(ProductRow.id)
        .group_by(ProductRow.id, ProductRow.name)
        .order_by(ProductRow.name.asc(), ProductRow.id)
    )
    count_subquery = product_ids_statement.order_by(None).subquery()
    count = int(session.scalar(select(func.count()).select_from(count_subquery)) or 0)
    selected_product_ids = list(
        session.scalars(
            product_ids_statement.offset((page - 1) * page_size).limit(page_size)
        ).all()
    )
    if not selected_product_ids:
        return [], count
    all_product_rows = (
        select(ProductRow, PublicCatalogOfferRow, SkuRow, ProductCategoryRow)
        .join(
            SkuRow,
            (SkuRow.tenant_id == ProductRow.tenant_id)
            & (SkuRow.product_id == ProductRow.id),
        )
        .join(
            PublicCatalogOfferRow,
            (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
            & (PublicCatalogOfferRow.sku_id == SkuRow.id),
        )
        .outerjoin(
            ProductCategoryRow,
            (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
            & (ProductCategoryRow.id == ProductRow.category_id)
            & (ProductCategoryRow.deleted_at.is_(None)),
        )
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(selected_product_ids),
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
            SkuRow.status == "ACTIVE",
            SkuRow.deleted_at.is_(None),
            PublicCatalogOfferRow.publication_status == "PUBLISHED",
            PublicCatalogOfferRow.deleted_at.is_(None),
        )
        .order_by(ProductRow.name.asc(), ProductRow.id, SkuRow.sku_code)
    )
    rows = session.execute(all_product_rows).all()
    grouped: dict[UUID, list[tuple[ProductRow, PublicCatalogOfferRow, SkuRow, ProductCategoryRow | None]]] = {}
    for product, offer, sku, category in rows:
        grouped.setdefault(product.id, []).append((product, offer, sku, category))
    return [grouped[product_id] for product_id in selected_product_ids if product_id in grouped], count


def get_subaccount_pricing(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> SubaccountPricingPage:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    policy = _pricing_policy(
        session,
        tenant_id=context.tenant_id,
        membership_id=child.id,
        create=False,
    )
    if policy is None:
        # A read must not create a row that can be rolled back when the request
        # session closes.  The first explicit save creates the durable policy.
        policy = SubaccountPricingPolicyRow(
            tenant_id=context.tenant_id,
            membership_id=child.id,
            markup_percent=Decimal("0"),
            hidden_product_ids=[],
        )
    overrides = {
        row.product_id: row
        for row in session.scalars(
            select(SubaccountProductPriceOverrideRow).where(
                SubaccountProductPriceOverrideRow.tenant_id == context.tenant_id,
                SubaccountProductPriceOverrideRow.membership_id == child.id,
                SubaccountProductPriceOverrideRow.is_active.is_(True),
                SubaccountProductPriceOverrideRow.deleted_at.is_(None),
            )
        ).all()
    }
    category_overrides = {
        row.category_id: row
        for row in session.scalars(
            select(SubaccountCategoryPriceOverrideRow).where(
                SubaccountCategoryPriceOverrideRow.tenant_id == context.tenant_id,
                SubaccountCategoryPriceOverrideRow.membership_id == child.id,
                SubaccountCategoryPriceOverrideRow.is_active.is_(True),
                SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
            )
        ).all()
    }
    groups, total = _pricing_product_rows(
        session,
        tenant_id=context.tenant_id,
        query=query,
        page=page,
        page_size=page_size,
    )
    sku_overrides = subaccount_sku_price_rules(
        session,
        tenant_id=context.tenant_id,
        membership_id=child.id,
        sku_ids={row[2].id for group in groups for row in group},
    )
    items: list[SubaccountProductPricingItem] = []
    category_markup_by_id = subaccount_category_price_rules(
        session,
        tenant_id=context.tenant_id,
        membership_id=child.id,
        category_ids={
            row[0].category_id
            for group in groups
            for row in group
            if row[0].category_id is not None
        },
    )
    for group in groups:
        product = group[0][0]
        prices = [Decimal(row[1].unit_price) for row in group]
        override = overrides.get(product.id)
        category = group[0][3]
        category_markup = (
            category_markup_by_id.get(category.id)
            if category is not None
            else None
        )
        effective = [
            effective_subaccount_price(
                price,
                markup_percent=Decimal(policy.markup_percent),
                override=override,
                category_markup_percent=category_markup,
                sku_override=sku_overrides.get(group[index][2].id),
            )
            for index, price in enumerate(prices)
        ]
        sku_override_count = sum(
            1 for row in group if row[2].id in sku_overrides
        )
        items.append(
            SubaccountProductPricingItem(
                product_id=product.id,
                product_code=product.product_code,
                product_name=product.name,
                category_id=category.id if category is not None else None,
                category_name=category.name if category is not None else None,
                sku_count=len(group),
                base_price_from=min(prices),
                base_price_to=max(prices),
                effective_price_from=min(effective),
                effective_price_to=max(effective),
                currency=str(group[0][1].currency).upper(),
                override_mode=override.pricing_mode if override else None,
                override_value=Decimal(override.value) if override else None,
                category_markup_percent=category_markup,
                sku_override_count=sku_override_count,
                sku_prices=[
                    SubaccountSkuPricingItem(
                        sku_id=row[2].id,
                        sku_code=row[2].sku_code,
                        base_price=Decimal(row[1].unit_price),
                        effective_price=effective_subaccount_price(
                            Decimal(row[1].unit_price),
                            markup_percent=Decimal(policy.markup_percent),
                            override=override,
                            category_markup_percent=category_markup,
                            sku_override=sku_overrides.get(row[2].id),
                        ),
                        currency=str(row[1].currency).upper(),
                        override_mode=(
                            sku_overrides[row[2].id].pricing_mode
                            if row[2].id in sku_overrides
                            else None
                        ),
                        override_value=(
                            Decimal(sku_overrides[row[2].id].value)
                            if row[2].id in sku_overrides
                            else None
                        ),
                    )
                    for row in group
                ],
                updated_at=max(row[0].updated_at for row in group),
            )
        )
    hidden_count = len(policy.hidden_product_ids or [])
    return SubaccountPricingPage(
        policy=SubaccountPricingPolicyResponse(
            membership_id=child.id,
            markup_percent=Decimal(policy.markup_percent),
            override_count=len(overrides),
            hidden_product_count=hidden_count,
            category_override_count=len(category_overrides),
            sku_override_count=_sku_override_count(
                session,
                tenant_id=context.tenant_id,
                membership_id=child.id,
            ),
        ),
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


def update_subaccount_pricing_policy(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    request: SubaccountPricingPolicyUpdate,
) -> SubaccountPricingPolicyResponse:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    policy = _pricing_policy(
        session, tenant_id=context.tenant_id, membership_id=child.id
    )
    policy.markup_percent = request.markup_percent
    policy.updated_at = utcnow()
    session.commit()
    override_count = int(
        session.scalar(
            select(func.count(SubaccountProductPriceOverrideRow.id)).where(
                SubaccountProductPriceOverrideRow.tenant_id == context.tenant_id,
                SubaccountProductPriceOverrideRow.membership_id == child.id,
                SubaccountProductPriceOverrideRow.is_active.is_(True),
                SubaccountProductPriceOverrideRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    category_override_count = int(
        session.scalar(
            select(func.count(SubaccountCategoryPriceOverrideRow.id)).where(
                SubaccountCategoryPriceOverrideRow.tenant_id == context.tenant_id,
                SubaccountCategoryPriceOverrideRow.membership_id == child.id,
                SubaccountCategoryPriceOverrideRow.is_active.is_(True),
                SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
            )
        )
        or 0
    )
    return SubaccountPricingPolicyResponse(
        membership_id=child.id,
        markup_percent=Decimal(policy.markup_percent),
        override_count=override_count,
        hidden_product_count=len(policy.hidden_product_ids or []),
        category_override_count=category_override_count,
        sku_override_count=_sku_override_count(
            session,
            tenant_id=context.tenant_id,
            membership_id=child.id,
        ),
    )


def update_subaccount_category_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    category_id: UUID,
    request: SubaccountCategoryPriceOverrideRequest,
) -> SubaccountPricingPolicyResponse:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    category = session.scalar(
        select(ProductCategoryRow).where(
            ProductCategoryRow.tenant_id == context.tenant_id,
            ProductCategoryRow.id == category_id,
            ProductCategoryRow.deleted_at.is_(None),
        )
    )
    if category is None:
        raise ApplicationError(
            "CATEGORY_NOT_FOUND", "Category was not found.", kind="not_found"
        )
    override = session.scalar(
        select(SubaccountCategoryPriceOverrideRow).where(
            SubaccountCategoryPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountCategoryPriceOverrideRow.membership_id == child.id,
            SubaccountCategoryPriceOverrideRow.category_id == category_id,
        )
    )
    if override is None:
        override = SubaccountCategoryPriceOverrideRow(
            tenant_id=context.tenant_id,
            membership_id=child.id,
            category_id=category_id,
            markup_percent=request.markup_percent,
            is_active=True,
        )
        session.add(override)
    else:
        override.markup_percent = request.markup_percent
        override.is_active = True
        override.deleted_at = None
    session.commit()
    policy = _pricing_policy(
        session, tenant_id=context.tenant_id, membership_id=child.id, create=False
    )
    return SubaccountPricingPolicyResponse(
        membership_id=child.id,
        markup_percent=Decimal(policy.markup_percent) if policy else Decimal("0"),
        override_count=int(
            session.scalar(
                select(func.count(SubaccountProductPriceOverrideRow.id)).where(
                    SubaccountProductPriceOverrideRow.tenant_id == context.tenant_id,
                    SubaccountProductPriceOverrideRow.membership_id == child.id,
                    SubaccountProductPriceOverrideRow.is_active.is_(True),
                    SubaccountProductPriceOverrideRow.deleted_at.is_(None),
                )
            )
            or 0
        ),
        hidden_product_count=len(policy.hidden_product_ids or []) if policy else 0,
        category_override_count=int(
            session.scalar(
                select(func.count(SubaccountCategoryPriceOverrideRow.id)).where(
                    SubaccountCategoryPriceOverrideRow.tenant_id == context.tenant_id,
                    SubaccountCategoryPriceOverrideRow.membership_id == child.id,
                    SubaccountCategoryPriceOverrideRow.is_active.is_(True),
                    SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
                )
            )
            or 0
        ),
        sku_override_count=_sku_override_count(
            session,
            tenant_id=context.tenant_id,
            membership_id=child.id,
        ),
    )


def clear_subaccount_category_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    category_id: UUID,
) -> None:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    override = session.scalar(
        select(SubaccountCategoryPriceOverrideRow).where(
            SubaccountCategoryPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountCategoryPriceOverrideRow.membership_id == child.id,
            SubaccountCategoryPriceOverrideRow.category_id == category_id,
            SubaccountCategoryPriceOverrideRow.deleted_at.is_(None),
        )
    )
    if override is not None:
        override.is_active = False
        override.deleted_at = utcnow()
        session.commit()


def set_subaccount_product_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    product_id: UUID,
    request: SubaccountProductPriceOverrideRequest,
) -> SubaccountProductPricingItem:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    product = session.scalar(
        select(ProductRow).where(
            ProductRow.id == product_id,
            ProductRow.tenant_id == context.tenant_id,
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
        )
    )
    if product is None:
        raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")
    override = session.scalar(
        select(SubaccountProductPriceOverrideRow).where(
            SubaccountProductPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountProductPriceOverrideRow.membership_id == child.id,
            SubaccountProductPriceOverrideRow.product_id == product_id,
        )
    )
    if override is None:
        override = SubaccountProductPriceOverrideRow(
            tenant_id=context.tenant_id,
            membership_id=child.id,
            product_id=product_id,
            pricing_mode=request.pricing_mode,
            value=request.value,
            is_active=True,
        )
        session.add(override)
    else:
        override.pricing_mode = request.pricing_mode
        override.value = request.value
        override.is_active = True
        override.deleted_at = None
    session.commit()
    # Search using stable product fields; UUIDs are deliberately not part of
    # the merchant-facing search fields.
    search_value = product.product_code or product.name
    page = get_subaccount_pricing(
        session,
        context=context,
        membership_id=child.id,
        query=search_value,
        page=1,
        page_size=20,
    )
    for item in page.items:
        if item.product_id == product_id:
            return item
    raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")


def clear_subaccount_product_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    product_id: UUID,
) -> None:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    override = session.scalar(
        select(SubaccountProductPriceOverrideRow).where(
            SubaccountProductPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountProductPriceOverrideRow.membership_id == child.id,
            SubaccountProductPriceOverrideRow.product_id == product_id,
            SubaccountProductPriceOverrideRow.deleted_at.is_(None),
        )
    )
    if override is not None:
        override.is_active = False
        override.deleted_at = utcnow()
        session.commit()


def set_subaccount_sku_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    sku_id: UUID,
    request: SubaccountSkuPriceOverrideRequest,
) -> SubaccountProductPricingItem:
    """Set a price for one concrete SKU and return the refreshed product row."""

    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    sku = session.scalar(
        select(SkuRow).where(
            SkuRow.id == sku_id,
            SkuRow.tenant_id == context.tenant_id,
            SkuRow.status == "ACTIVE",
            SkuRow.deleted_at.is_(None),
        )
    )
    if sku is None:
        raise ApplicationError("SKU_NOT_FOUND", "SKU was not found.", kind="not_found")
    product = session.scalar(
        select(ProductRow).where(
            ProductRow.id == sku.product_id,
            ProductRow.tenant_id == context.tenant_id,
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
        )
    )
    if product is None:
        raise ApplicationError(
            "PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found"
        )
    override = session.scalar(
        select(SubaccountSkuPriceOverrideRow).where(
            SubaccountSkuPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountSkuPriceOverrideRow.membership_id == child.id,
            SubaccountSkuPriceOverrideRow.sku_id == sku_id,
        )
    )
    if override is None:
        override = SubaccountSkuPriceOverrideRow(
            tenant_id=context.tenant_id,
            membership_id=child.id,
            sku_id=sku_id,
            pricing_mode=request.pricing_mode,
            value=request.value,
            is_active=True,
        )
        session.add(override)
    else:
        override.pricing_mode = request.pricing_mode
        override.value = request.value
        override.is_active = True
        override.deleted_at = None
    session.commit()
    page = get_subaccount_pricing(
        session,
        context=context,
        membership_id=child.id,
        query=product.product_code or product.name,
        page=1,
        page_size=20,
    )
    for item in page.items:
        if item.product_id == product.id:
            return item
    raise ApplicationError("PRODUCT_NOT_FOUND", "Product was not found.", kind="not_found")


def clear_subaccount_sku_price_override(
    session: Session,
    *,
    context: RequestContext,
    membership_id: UUID,
    sku_id: UUID,
) -> None:
    child = _parent_child_membership(
        session, context=context, membership_id=membership_id
    )
    override = session.scalar(
        select(SubaccountSkuPriceOverrideRow).where(
            SubaccountSkuPriceOverrideRow.tenant_id == context.tenant_id,
            SubaccountSkuPriceOverrideRow.membership_id == child.id,
            SubaccountSkuPriceOverrideRow.sku_id == sku_id,
            SubaccountSkuPriceOverrideRow.deleted_at.is_(None),
        )
    )
    if override is not None:
        override.is_active = False
        override.deleted_at = utcnow()
        session.commit()


def get_customer_portal_overview(
    session: Session,
    *,
    context: RequestContext,
) -> CustomerPortalOverview:
    _require_customer_portal(context)
    membership, tenant, user = session.execute(
        select(MembershipRow, TenantRow, UserRow)
        .join(TenantRow, TenantRow.id == MembershipRow.tenant_id)
        .join(UserRow, UserRow.id == MembershipRow.user_id)
        .where(MembershipRow.id == context.membership_id)
    ).one()
    if "customer_portal.order_view_self" in context.permissions:
        count, last_order = session.execute(
            select(
                func.count(PublicQuoteDraftRow.id),
                func.max(PublicQuoteDraftRow.created_at),
            ).where(
                PublicQuoteDraftRow.tenant_id == context.tenant_id,
                PublicQuoteDraftRow.submitted_by_membership_id == membership.id,
            )
        ).one()
    else:
        count, last_order = 0, None
    return CustomerPortalOverview(
        display_name=user.display_name,
        tenant_name=tenant.name,
        tenant_slug=tenant.slug,
        account_status=membership.status,
        order_count=int(count or 0),
        last_order_at=last_order,
    )


def list_customer_portal_orders(
    session: Session,
    *,
    context: RequestContext,
) -> list[CustomerPortalOrderSummary]:
    _require_customer_portal(context, "customer_portal.order_view_self")
    rows = session.scalars(
        select(PublicQuoteDraftRow)
        .where(
            PublicQuoteDraftRow.tenant_id == context.tenant_id,
            PublicQuoteDraftRow.submitted_by_membership_id == context.membership_id,
        )
        .order_by(PublicQuoteDraftRow.created_at.desc(), PublicQuoteDraftRow.id)
        .limit(100)
    ).all()
    return [
        CustomerPortalOrderSummary(
            id=row.id,
            quote_number=row.request_number,
            status=row.status,
            customer_name=row.customer_name,
            customer_company=row.customer_company,
            currency=row.currency,
            total_amount=row.estimated_total,
            created_at=row.created_at,
            valid_until=row.expires_at,
        )
        for row in rows
    ]
    CustomerSubaccountAccessUpdate,
