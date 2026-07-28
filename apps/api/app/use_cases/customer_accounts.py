from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..customer_accounts_schemas import (
    CustomerPortalOrderSummary,
    CustomerPortalOverview,
    CustomerSubaccountCreate,
    CustomerSubaccountDashboard,
    CustomerSubaccountOrderPage,
    CustomerSubaccountOrderSummary,
    CustomerSubaccountStatusUpdate,
    CustomerSubaccountSummary,
)
from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import (
    CustomerAccountAccessEventRow,
    LocalAccountCredentialRow,
    MembershipRoleRow,
    MembershipRow,
    TenantRow,
    UserRow,
)
from ..model_mixins import utcnow
from ..public_catalog_models import PublicQuoteDraftRow
from ..saas_seed import ensure_tenant_rbac
from ..services.auth.dependencies import RequestContext
from ..services.auth.local_credentials import normalize_local_identifier
from ..services.auth.password_accounts import (
    PasswordIdentityProvisioningError,
    password_is_valid,
    provision_password_identity,
)


_CUSTOMER_SCOPE = "CUSTOMER_SUBACCOUNT"
_PORTAL_ROLE = "CUSTOMER_SUBACCOUNT"


def _require_parent(context: RequestContext) -> None:
    if context.account_scope != "STAFF" or "customer_portal.subaccount_manage" not in context.permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            "Customer subaccount management permission is required.",
            kind="forbidden",
        )


def _require_customer_portal(context: RequestContext) -> None:
    if (
        context.account_scope != _CUSTOMER_SCOPE
        or "customer_portal.access" not in context.permissions
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
) -> tuple[dict[UUID, tuple[int, object | None]], dict[UUID, tuple[int, object | None]]]:
    if not membership_ids:
        return {}, {}
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
        )
        .where(
            PublicQuoteDraftRow.tenant_id == tenant_id,
            PublicQuoteDraftRow.submitted_by_membership_id.in_(membership_ids),
        )
        .group_by(PublicQuoteDraftRow.submitted_by_membership_id)
    ).all()
    return (
        {row[0]: (int(row[1] or 0), row[2]) for row in access_rows},
        {row[0]: (int(row[1] or 0), row[2]) for row in order_rows},
    )


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
    access, orders = _subaccount_metrics(
        session, tenant_id=tenant_id, membership_ids=membership_ids
    )
    return [
        CustomerSubaccountSummary(
            id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            login_identifier=membership.login_identifier or user.email_normalized or "—",
            email=user.email_normalized,
            status=membership.status,
            created_at=membership.created_at,
            last_login_at=user.last_login_at or access.get(membership.id, (0, None))[1],
            login_count_30d=access.get(membership.id, (0, None))[0],
            order_count=orders.get(membership.id, (0, None))[0],
            last_order_at=orders.get(membership.id, (0, None))[1],
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
            "Password must be 8-128 characters and include both letters and numbers.",
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
    count, last_order = session.execute(
        select(
            func.count(PublicQuoteDraftRow.id),
            func.max(PublicQuoteDraftRow.created_at),
        ).where(
            PublicQuoteDraftRow.tenant_id == context.tenant_id,
            PublicQuoteDraftRow.submitted_by_membership_id == membership.id,
        )
    ).one()
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
    _require_customer_portal(context)
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
