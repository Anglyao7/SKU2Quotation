from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import (
    LocalAccountCredentialRow,
    MerchantIdentityProfileRow,
    MembershipRoleRow,
    MembershipRow,
    TenantSubscriptionRow,
    TenantRow,
    UserRow,
)
from ..model_mixins import utcnow
from ..platform_admin_schemas import (
    PlatformMerchantIdentityCreate,
    PlatformMerchantIdentityProfile,
    PlatformMerchantIdentityUpdate,
    PlatformMerchantDailyMetric,
    PlatformMerchantMonitoring,
    PlatformMerchantRecentQuote,
    PlatformMerchantStatusMetric,
    PlatformMerchantSubaccountDetail,
    PlatformMerchantSubaccountSummary,
    PlatformMemberInvitation,
    PlatformMemberInvitationCreate,
    PlatformMerchantOwnerAccount,
    PlatformMerchantOwnerCreate,
    PlatformMerchantOwnerPasswordReset,
    PlatformMerchantOwnerPasswordResetResponse,
    PlatformTenantCreate,
    PlatformTenantDetail,
    PlatformTenantSubscriptionUpdate,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from ..customer_accounts_schemas import CUSTOMER_SUBACCOUNT_MODULES, normalize_modules
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import platform_admin_repository as repository
from ..saas_seed import ensure_tenant_rbac
from ..inventory_seed import ensure_default_warehouse
from ..services.auth.dependencies import RequestContext
from ..services.auth.service import AuthError, reset_password_for_user
from ..services.member_invitations import invite_tenant_member as create_member_invitation
from ..services.storefront_paths import (
    allocate_storefront_slug,
    exact_storefront_slug_is_available,
)
from ..services.sku_codes import derive_merchant_sku_prefix
from ..services.auth.local_credentials import normalize_local_identifier
from ..services.auth.password_accounts import (
    PasswordIdentityProvisioningError,
    password_is_valid,
    provision_password_identity,
)
from ..tenant_slugs import (
    is_reserved_tenant_slug,
    storefront_slug_from_name,
)
from ..tenant_modules import (
    SYSTEM_MERCHANT_IDENTITY_CODES,
    TENANT_MODULE_CODES,
    effective_tenant_modules,
    normalized_merchant_identity,
    normalized_module_access_mode,
    normalized_tenant_modules,
)
from ..tenant_subscriptions import (
    default_sku_limit,
    default_subscription_expiry,
    normalized_utc,
    subscription_status,
)


def _require_platform_admin(context: RequestContext) -> None:
    if not context.is_platform_admin:
        raise ApplicationError(
            "PLATFORM_ADMIN_REQUIRED",
            "Platform administrator access is required.",
            kind="forbidden",
        )


@contextmanager
def _tenant_scope(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
) -> Iterator[None]:
    """Temporarily bind one tenant for tenant-scoped aggregate reads and writes."""

    set_request_context(
        session,
        organization_id=context.organization_id,
        tenant_id=tenant_id,
        user_id=context.user_id,
    )
    try:
        yield
    finally:
        set_request_context(
            session,
            organization_id=context.organization_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
        )


def _tenant_effective_modules(
    session: Session,
    tenant: TenantRow,
) -> tuple[str, str, tuple[str, ...]]:
    identity_code = normalized_merchant_identity(tenant.identity_code)
    access_mode = (
        "INHERIT"
        if identity_code == "ADMIN"
        else normalized_module_access_mode(tenant.module_access_mode)
    )
    identity_profile = session.get(MerchantIdentityProfileRow, identity_code)
    modules = effective_tenant_modules(
        identity_code=identity_code,
        access_mode=access_mode,
        custom_modules=tenant.enabled_modules,
        identity_default_modules=(
            identity_profile.default_modules
            if identity_profile is not None
            else None
        ),
    )
    return identity_code, access_mode, modules


def _identity_profile_or_error(
    session: Session,
    identity_code: object,
) -> MerchantIdentityProfileRow:
    normalized_code = normalized_merchant_identity(identity_code)
    profile = session.get(MerchantIdentityProfileRow, normalized_code)
    if profile is None or profile.deleted_at is not None:
        raise ApplicationError(
            "MERCHANT_IDENTITY_NOT_FOUND",
            "Merchant identity was not found.",
            kind="not_found",
        )
    return profile


def _grant_platform_access_to_admin_merchant_staff(
    session: Session,
    *,
    context: RequestContext,
    tenant: TenantRow,
) -> None:
    """Keep the legacy database flag aligned for PostgreSQL policy helpers.

    Runtime authorization is resolved from the active merchant identity. The
    persisted flag remains a compatibility projection for constrained database
    functions and historical RLS policies.
    """

    if normalized_merchant_identity(tenant.identity_code) != "ADMIN":
        return
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text(
                "SELECT public.atc_grant_tenant_admin_identity("
                ":actor_user_id, :actor_tenant_id, :target_tenant_id)"
            ),
            {
                "actor_user_id": context.user_id,
                "actor_tenant_id": context.tenant_id,
                "target_tenant_id": tenant.id,
            },
        )
        return
    staff_user_ids = select(MembershipRow.user_id).where(
        MembershipRow.tenant_id == tenant.id,
        MembershipRow.account_scope == "STAFF",
        MembershipRow.status == "active",
        MembershipRow.deleted_at.is_(None),
    )
    session.execute(
        update(UserRow)
        .where(
            UserRow.id.in_(staff_user_ids),
            UserRow.deleted_at.is_(None),
        )
        .values(is_platform_admin=True)
    )


def _ensure_an_active_admin_merchant_remains(
    session: Session,
    *,
    tenant: TenantRow,
    next_identity_code: object,
    next_status: str,
) -> None:
    if (
        normalized_merchant_identity(tenant.identity_code) != "ADMIN"
        or (
            normalized_merchant_identity(next_identity_code) == "ADMIN"
            and next_status == "active"
        )
    ):
        return
    another_admin = session.scalar(
        select(TenantRow.id).where(
            TenantRow.id != tenant.id,
            TenantRow.identity_code == "ADMIN",
            TenantRow.status == "active",
            TenantRow.deleted_at.is_(None),
        ).limit(1)
    )
    if another_admin is None:
        raise ApplicationError(
            "LAST_ADMIN_MERCHANT_REQUIRED",
            "At least one active administrator merchant must remain.",
            kind="conflict",
        )


def _summary(
    session: Session,
    *,
    context: RequestContext,
    tenant: TenantRow,
) -> PlatformTenantSummary:
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        profile = repository.get_public_profile(session, tenant.id)
        sku_count, quote_count = repository.tenant_counts(session, tenant.id)
        owner = repository.get_tenant_owner_account(session, tenant.id)
    subscription = repository.get_tenant_subscription(session, tenant.id)
    subscription_started_at = (
        subscription.started_at if subscription is not None else tenant.created_at
    )
    subscription_tier = (
        subscription.subscription_tier if subscription is not None else "TRIAL"
    )
    subscription_expires_at = (
        subscription.expires_at
        if subscription is not None
        else default_subscription_expiry("TRIAL", started_at=subscription_started_at)
    )
    sku_limit = (
        subscription.sku_limit
        if subscription is not None
        else default_sku_limit("TRIAL")
    )
    owner_account = (
        _owner_account_summary(*owner)
        if owner is not None
        else None
    )
    identity_code, access_mode, effective_modules = _tenant_effective_modules(
        session,
        tenant,
    )
    return PlatformTenantSummary(
        id=tenant.id,
        organization_id=tenant.organization_id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        active=tenant.status == "active",
        default_locale=tenant.default_locale,
        default_currency=tenant.default_currency,
        timezone=tenant.timezone,
        identity_code=identity_code,
        module_access_mode=access_mode,
        enabled_modules=list(effective_modules),
        module_overrides=(
            list(normalized_tenant_modules(tenant.enabled_modules))
            if access_mode == "CUSTOM"
            else None
        ),
        subscription_tier=subscription_tier,  # type: ignore[arg-type]
        subscription_started_at=subscription_started_at,
        subscription_expires_at=subscription_expires_at,
        subscription_status=subscription_status(
            subscription_expires_at,
            now=utcnow(),
        ),
        sku_limit=sku_limit,
        sku_remaining=(
            None if sku_limit is None else max(0, sku_limit - sku_count)
        ),
        contact_email=profile.contact_email if profile else None,
        sku_count=sku_count,
        quote_count=quote_count,
        owner_account=owner_account,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


def _owner_account_summary(
    membership: MembershipRow,
    user: UserRow,
) -> PlatformMerchantOwnerAccount:
    """Shape a platform-only view without ever returning password material."""

    return PlatformMerchantOwnerAccount(
        user_id=membership.user_id,
        membership_id=membership.id,
        display_name=user.display_name,
        login_identifier=membership.login_identifier,
        email=user.email_normalized,
        status=membership.status,  # type: ignore[arg-type]
        created_at=membership.created_at,
    )


def list_tenants(
    session: Session,
    *,
    context: RequestContext,
) -> list[PlatformTenantSummary]:
    _require_platform_admin(context)
    return [_summary(session, context=context, tenant=row) for row in repository.list_tenants(session)]


_SUBACCOUNT_CAPABILITY_PERMISSIONS = {
    "catalog": "customer_portal.access",
    "submit_orders": "customer_portal.order_create",
    "view_orders": "customer_portal.order_view_self",
}
_QUOTE_STATUSES = (
    "PENDING_CONFIRMATION",
    "CONFIRMED",
    "COMPLETED",
    "CANCELLED",
    "EXPIRED",
)


def _tenant_or_error(session: Session, tenant_id: UUID) -> TenantRow:
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None or tenant.deleted_at is not None:
        raise ApplicationError(
            "TENANT_NOT_FOUND",
            "Tenant was not found.",
            kind="not_found",
        )
    return tenant


def _tenant_reporting_window(
    tenant: TenantRow,
    *,
    days: int = 30,
) -> tuple[datetime, datetime, ZoneInfo]:
    try:
        zone = ZoneInfo(tenant.timezone or "UTC")
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    now = utcnow()
    local_end_date = now.astimezone(zone).date()
    local_start_date = local_end_date - timedelta(days=days - 1)
    started_at = datetime.combine(local_start_date, time.min, tzinfo=zone).astimezone(UTC)
    ended_at = datetime.combine(
        local_end_date + timedelta(days=1),
        time.min,
        tzinfo=zone,
    ).astimezone(UTC)
    return started_at, ended_at, zone


def _subaccount_capabilities(value: object) -> list[str]:
    if not isinstance(value, list):
        return list(_SUBACCOUNT_CAPABILITY_PERMISSIONS)
    permissions = {str(code) for code in value}
    capabilities = [
        capability
        for capability, permission in _SUBACCOUNT_CAPABILITY_PERMISSIONS.items()
        if permission in permissions
    ]
    if "catalog" not in capabilities:
        capabilities.insert(0, "catalog")
    return capabilities


def _subaccount_modules(value: object) -> list[str]:
    """Project a child permission ceiling into the workspace modules it gets.

    The platform console used to show the legacy ``catalog / submit_orders /
    view_orders`` capability names, which made a real operator account look
    like a guest.  Keep the old projection for API compatibility, but expose
    the module scope as the source of truth for the new UI.  NULL and the
    legacy three-permission value both mean the historical all-module default.
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
    # Keep the ordering stable and guarantee a usable product landing area.
    return normalize_modules(list(selected))


def _merchant_subaccounts(
    session: Session,
    *,
    tenant: TenantRow,
    started_at: datetime,
) -> list[PlatformMerchantSubaccountSummary]:
    rows = repository.list_tenant_subaccounts(session, tenant.id)
    membership_ids = [membership.id for membership, _user in rows]
    parent_ids = list(
        {
            membership.parent_membership_id
            for membership, _user in rows
            if membership.parent_membership_id is not None
        }
    )
    parent_names = repository.membership_display_names(
        session,
        tenant_id=tenant.id,
        membership_ids=parent_ids,
    )
    access, quotes = repository.subaccount_activity_metrics(
        session,
        tenant_id=tenant.id,
        membership_ids=membership_ids,
        started_at=started_at,
    )
    return [
        PlatformMerchantSubaccountSummary(
            id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            login_identifier=(
                membership.login_identifier
                or user.email_normalized
                or "—"
            ),
            email=user.email_normalized,
            status=membership.status,  # type: ignore[arg-type]
            modules=_subaccount_modules(membership.permission_overrides),
            capabilities=_subaccount_capabilities(
                membership.permission_overrides
            ),  # type: ignore[arg-type]
            parent_membership_id=membership.parent_membership_id,
            parent_display_name=parent_names.get(membership.parent_membership_id),
            created_at=membership.created_at,
            last_login_at=(
                user.last_login_at
                or access.get(membership.id, (0, None))[1]
            ),
            login_count_30d=access.get(membership.id, (0, None))[0],
            quote_count=quotes.get(membership.id, (0, None))[0],
            last_quote_at=quotes.get(membership.id, (0, None))[1],
        )
        for membership, user in rows
    ]


def _merchant_monitoring(
    session: Session,
    *,
    tenant: TenantRow,
    subaccounts: list[PlatformMerchantSubaccountSummary],
    started_at: datetime,
    ended_at: datetime,
    zone: ZoneInfo,
    days: int = 30,
) -> PlatformMerchantMonitoring:
    now = utcnow()
    status_counts = repository.quote_status_counts(session, tenant.id)
    quote_dates = repository.quote_dates_since(
        session,
        tenant_id=tenant.id,
        started_at=started_at,
    )
    start_date = started_at.astimezone(zone).date()
    end_date = (ended_at - timedelta(microseconds=1)).astimezone(zone).date()
    quote_daily: dict[date, int] = {}
    for value in quote_dates:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        local_date = normalized.astimezone(zone).date()
        quote_daily[local_date] = quote_daily.get(local_date, 0) + 1
    product_daily = repository.product_view_daily(
        session,
        tenant_id=tenant.id,
        start_date=start_date,
        end_date=end_date,
    )
    dates = [start_date + timedelta(days=offset) for offset in range(days)]
    sku_count, _quote_count = repository.tenant_counts(session, tenant.id)
    return PlatformMerchantMonitoring(
        generated_at=now,
        period_days=days,
        quotes_total=sum(status_counts.values()),
        quotes_period=len(quote_dates),
        quotes_pending=status_counts.get("PENDING_CONFIRMATION", 0),
        quotes_confirmed=status_counts.get("CONFIRMED", 0),
        quotes_completed=status_counts.get("COMPLETED", 0),
        quotes_cancelled=status_counts.get("CANCELLED", 0),
        skus_total=sku_count,
        subaccounts_total=len(subaccounts),
        subaccounts_active=sum(row.status == "active" for row in subaccounts),
        storefront_visitors_period=repository.storefront_visitor_count(
            session,
            tenant_id=tenant.id,
            started_at=started_at,
            ended_at=ended_at,
        ),
        product_views_period=sum(product_daily.values()),
        last_quote_at=repository.last_quote_at(session, tenant.id),
        quote_statuses=[
            PlatformMerchantStatusMetric(
                status=status,  # type: ignore[arg-type]
                count=status_counts.get(status, 0),
            )
            for status in _QUOTE_STATUSES
        ],
        quote_trend=[
            PlatformMerchantDailyMetric(date=value, count=quote_daily.get(value, 0))
            for value in dates
        ],
        product_view_trend=[
            PlatformMerchantDailyMetric(date=value, count=product_daily.get(value, 0))
            for value in dates
        ],
    )


def get_tenant_detail(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
) -> PlatformTenantDetail:
    _require_platform_admin(context)
    tenant = _tenant_or_error(session, tenant_id)
    started_at, ended_at, zone = _tenant_reporting_window(tenant)
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        subaccounts = _merchant_subaccounts(
            session,
            tenant=tenant,
            started_at=started_at,
        )
        monitoring = _merchant_monitoring(
            session,
            tenant=tenant,
            subaccounts=subaccounts,
            started_at=started_at,
            ended_at=ended_at,
            zone=zone,
        )
    return PlatformTenantDetail(
        merchant=_summary(session, context=context, tenant=tenant),
        monitoring=monitoring,
        subaccounts=subaccounts,
    )


def get_tenant_subaccount_detail(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    membership_id: UUID,
) -> PlatformMerchantSubaccountDetail:
    _require_platform_admin(context)
    tenant = _tenant_or_error(session, tenant_id)
    started_at, _ended_at, _zone = _tenant_reporting_window(tenant)
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        accounts = _merchant_subaccounts(
            session,
            tenant=tenant,
            started_at=started_at,
        )
        account = next((row for row in accounts if row.id == membership_id), None)
        if account is None:
            raise ApplicationError(
                "MERCHANT_SUBACCOUNT_NOT_FOUND",
                "Customer subaccount was not found.",
                kind="not_found",
            )
        recent_quotes = [
            PlatformMerchantRecentQuote(
                id=row.id,
                quote_number=row.quotation_number or row.request_number,
                status=row.status,  # type: ignore[arg-type]
                customer_name=row.customer_name,
                customer_company=row.customer_company,
                currency=row.currency,
                total_amount=row.estimated_total,
                created_at=row.created_at,
                valid_until=row.expires_at,
            )
            for row in repository.list_recent_subaccount_quotes(
                session,
                tenant_id=tenant.id,
                membership_id=membership_id,
            )
        ]
    return PlatformMerchantSubaccountDetail(
        merchant=_summary(session, context=context, tenant=tenant),
        account=account,
        recent_quotes=recent_quotes,
    )


def _identity_profile_response(
    row: MerchantIdentityProfileRow,
) -> PlatformMerchantIdentityProfile:
    return PlatformMerchantIdentityProfile(
        code=normalized_merchant_identity(row.code),
        name=row.name,
        enabled_modules=list(normalized_tenant_modules(row.default_modules)),
        is_system=row.is_system,
        editable=row.code != "ADMIN",
        version=row.version,
        updated_at=row.updated_at,
    )


def list_merchant_identities(
    session: Session,
    *,
    context: RequestContext,
) -> list[PlatformMerchantIdentityProfile]:
    _require_platform_admin(context)
    rows = list(
        session.scalars(
            select(MerchantIdentityProfileRow).where(
                MerchantIdentityProfileRow.deleted_at.is_(None),
            )
        ).all()
    )
    system_order = {
        code: index for index, code in enumerate(SYSTEM_MERCHANT_IDENTITY_CODES)
    }
    rows.sort(
        key=lambda row: (
            system_order.get(row.code, len(system_order)),
            row.created_at,
            row.code,
        )
    )
    return [_identity_profile_response(row) for row in rows]


def create_merchant_identity(
    session: Session,
    *,
    context: RequestContext,
    request: PlatformMerchantIdentityCreate,
) -> PlatformMerchantIdentityProfile:
    _require_platform_admin(context)
    code = f"CUSTOM_{uuid4().hex[:8].upper()}"
    while session.get(MerchantIdentityProfileRow, code) is not None:
        code = f"CUSTOM_{uuid4().hex[:8].upper()}"
    profile = MerchantIdentityProfileRow(
        code=code,
        name=request.name,
        default_modules=list(request.enabled_modules),
        is_system=False,
        version=1,
        updated_by_user_id=context.user_id,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return _identity_profile_response(profile)


def update_merchant_identity(
    session: Session,
    *,
    context: RequestContext,
    identity_code: str,
    request: PlatformMerchantIdentityUpdate,
) -> PlatformMerchantIdentityProfile:
    _require_platform_admin(context)
    normalized_code = identity_code.strip().upper()
    profile = _identity_profile_or_error(session, normalized_code)
    if normalized_code == "ADMIN":
        raise ApplicationError(
            "ADMIN_IDENTITY_IMMUTABLE",
            "The administrator identity always has full access and cannot be edited.",
            kind="conflict",
        )
    modules_changed = False
    changed = False
    if request.name is not None and request.name != profile.name:
        profile.name = request.name
        changed = True
    if request.enabled_modules is not None:
        next_modules = list(request.enabled_modules)
        modules_changed = next_modules != list(
            normalized_tenant_modules(profile.default_modules)
        )
        if modules_changed:
            profile.default_modules = next_modules
            changed = True
    if changed:
        profile.version += 1
        profile.updated_by_user_id = context.user_id
        profile.updated_at = utcnow()
    if modules_changed:
        inherited_tenant_ids = list(
            session.scalars(
                select(TenantRow.id).where(
                    TenantRow.identity_code == normalized_code,
                    TenantRow.module_access_mode == "INHERIT",
                    TenantRow.deleted_at.is_(None),
                )
            ).all()
        )
        for tenant_id in inherited_tenant_ids:
            with _tenant_scope(session, context=context, tenant_id=tenant_id):
                session.execute(
                    update(MembershipRow)
                    .where(
                        MembershipRow.tenant_id == tenant_id,
                        MembershipRow.status.in_(("active", "invited", "suspended")),
                        MembershipRow.deleted_at.is_(None),
                    )
                    .values(permission_version=MembershipRow.permission_version + 1)
                )
    session.commit()
    return _identity_profile_response(profile)


def delete_merchant_identity(
    session: Session,
    *,
    context: RequestContext,
    identity_code: str,
) -> None:
    _require_platform_admin(context)
    profile = _identity_profile_or_error(session, identity_code)
    if profile.is_system or profile.code in SYSTEM_MERCHANT_IDENTITY_CODES:
        raise ApplicationError(
            "SYSTEM_IDENTITY_IMMUTABLE",
            "System identities cannot be deleted.",
            kind="conflict",
        )
    tenant_id = session.scalar(
        select(TenantRow.id).where(
            TenantRow.identity_code == profile.code,
            TenantRow.deleted_at.is_(None),
        ).limit(1)
    )
    if tenant_id is not None:
        raise ApplicationError(
            "IDENTITY_IN_USE",
            "Move merchants to another identity before deleting this identity.",
            kind="conflict",
        )
    profile.deleted_at = utcnow()
    profile.updated_at = utcnow()
    profile.updated_by_user_id = context.user_id
    session.commit()


def create_tenant(
    session: Session,
    *,
    context: RequestContext,
    request: PlatformTenantCreate,
) -> PlatformTenantSummary:
    _require_platform_admin(context)
    _identity_profile_or_error(session, request.identity_code)
    base_slug = (
        request.slug.casefold()
        if request.slug
        else storefront_slug_from_name(request.name)
    )
    if is_reserved_tenant_slug(base_slug):
        raise ApplicationError(
            "TENANT_SLUG_RESERVED",
            "This storefront slug is reserved by the platform.",
            kind="invalid",
        )
    if request.slug and not exact_storefront_slug_is_available(
        session,
        slug=base_slug,
    ):
        raise ApplicationError(
            "TENANT_SLUG_EXISTS",
            "This storefront slug is already in use.",
            kind="conflict",
        )
    slug = (
        base_slug
        if request.slug
        else allocate_storefront_slug(session, base=base_slug)
    )
    subscription_started_at = utcnow()
    is_admin_identity = normalized_merchant_identity(request.identity_code) == "ADMIN"
    tenant = TenantRow(
        organization_id=context.organization_id,
        name=request.name,
        slug=slug,
        sku_prefix=derive_merchant_sku_prefix(request.name, slug=slug),
        default_locale=request.default_locale,
        default_currency=request.default_currency,
        timezone=request.timezone,
        identity_code=request.identity_code,
        module_access_mode=("INHERIT" if is_admin_identity else request.module_access_mode),
        enabled_modules=(list(TENANT_MODULE_CODES) if is_admin_identity else list(request.enabled_modules)),
        status="active" if request.active else "suspended",
    )
    session.add(tenant)
    try:
        session.flush()
        session.add(
            TenantSubscriptionRow(
                tenant_id=tenant.id,
                subscription_tier="TRIAL",
                started_at=subscription_started_at,
                expires_at=default_subscription_expiry(
                    "TRIAL",
                    started_at=subscription_started_at,
                ),
                sku_limit=default_sku_limit("TRIAL"),
            )
        )
        with _tenant_scope(session, context=context, tenant_id=tenant.id):
            session.add(
                TenantPublicProfileRow(
                    tenant_id=tenant.id,
                    slug=tenant.slug,
                    contact_email=request.contact_email or None,
                    publication_status="PUBLISHED" if request.active else "SUSPENDED",
                )
            )
            ensure_tenant_rbac(session, tenant_id=tenant.id)
            ensure_default_warehouse(session, tenant_id=tenant.id)
            session.flush()
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "TENANT_SLUG_EXISTS",
            "This storefront slug is already in use.",
            kind="conflict",
        ) from exc
    return _summary(session, context=context, tenant=tenant)


def update_tenant_subscription(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: PlatformTenantSubscriptionUpdate,
) -> PlatformTenantSummary:
    _require_platform_admin(context)
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")

    now = utcnow()
    expires_at = normalized_utc(request.subscription_expires_at)
    if expires_at <= now:
        raise ApplicationError(
            "SUBSCRIPTION_EXPIRY_MUST_BE_FUTURE",
            "Subscription expiry must be later than the current time.",
            kind="invalid",
        )

    subscription = repository.get_tenant_subscription(session, tenant.id)
    if subscription is None:
        subscription = TenantSubscriptionRow(
            tenant_id=tenant.id,
            subscription_tier=request.subscription_tier,
            started_at=now,
            expires_at=expires_at,
            sku_limit=(
                request.sku_limit
                if "sku_limit" in request.model_fields_set
                else default_sku_limit(request.subscription_tier)
            ),
        )
        session.add(subscription)
    current_expiry = normalized_utc(subscription.expires_at)
    tier_changed = subscription.subscription_tier != request.subscription_tier
    if tier_changed or current_expiry <= now:
        subscription.started_at = now
    if expires_at <= normalized_utc(subscription.started_at):
        raise ApplicationError(
            "SUBSCRIPTION_EXPIRY_BEFORE_START",
            "Subscription expiry must be later than its start time.",
            kind="invalid",
        )
    subscription.subscription_tier = request.subscription_tier
    subscription.expires_at = expires_at
    if "sku_limit" in request.model_fields_set:
        subscription.sku_limit = request.sku_limit
    elif tier_changed:
        subscription.sku_limit = default_sku_limit(request.subscription_tier)
    session.commit()
    return _summary(session, context=context, tenant=tenant)


def update_tenant(
    session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: PlatformTenantUpdate,
) -> PlatformTenantSummary:
    _require_platform_admin(context)
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")
    if request.identity_code is not None:
        _identity_profile_or_error(session, request.identity_code)
    if request.active is False and tenant.id == context.tenant_id:
        raise ApplicationError(
            "ACTIVE_TENANT_SUSPENSION_FORBIDDEN",
            "Switch to another active workspace before suspending this tenant.",
            kind="conflict",
        )
    _ensure_an_active_admin_merchant_remains(
        session,
        tenant=tenant,
        next_identity_code=request.identity_code or tenant.identity_code,
        next_status=(
            "active"
            if request.active is True
            else "suspended"
            if request.active is False
            else tenant.status
        ),
    )
    if request.name is not None:
        base_slug = storefront_slug_from_name(request.name)
        next_slug = allocate_storefront_slug(
            session,
            base=base_slug,
            exclude_tenant_id=tenant.id,
        )
        tenant.name = request.name
    else:
        next_slug = tenant.slug
    if request.active is not None:
        tenant.status = "active" if request.active else "suspended"
    if request.default_locale is not None:
        tenant.default_locale = request.default_locale
    if request.default_currency is not None:
        tenant.default_currency = request.default_currency
    if request.timezone is not None:
        tenant.timezone = request.timezone
    previous_effective_modules = _tenant_effective_modules(session, tenant)[2]
    previous_access_mode = normalized_module_access_mode(tenant.module_access_mode)
    if request.identity_code is not None:
        tenant.identity_code = request.identity_code
    if request.module_access_mode is not None:
        if (
            request.module_access_mode == "CUSTOM"
            and previous_access_mode == "INHERIT"
            and "enabled_modules" not in request.model_fields_set
        ):
            tenant.enabled_modules = list(previous_effective_modules)
        tenant.module_access_mode = request.module_access_mode
    if "enabled_modules" in request.model_fields_set:
        if request.enabled_modules is None:
            raise ApplicationError(
                "TENANT_MODULES_REQUIRED",
                "Enabled modules must be a list.",
                kind="invalid",
            )
        tenant.enabled_modules = list(request.enabled_modules or [])
        if "module_access_mode" not in request.model_fields_set:
            # Backward-compatible behavior for the existing module endpoint:
            # providing a list means the merchant is intentionally customized.
            tenant.module_access_mode = "CUSTOM"
    if normalized_merchant_identity(tenant.identity_code) == "ADMIN":
        tenant.module_access_mode = "INHERIT"
        tenant.enabled_modules = list(TENANT_MODULE_CODES)
    modules_changed = (
        previous_effective_modules
        != _tenant_effective_modules(session, tenant)[2]
    )
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        profile = repository.get_public_profile(session, tenant.id)
        if profile is None:
            profile = TenantPublicProfileRow(
                tenant_id=tenant.id,
                slug=tenant.slug,
                publication_status="PUBLISHED" if tenant.status == "active" else "SUSPENDED",
            )
            session.add(profile)
        if next_slug != tenant.slug:
            aliases: list[str] = []
            seen = {next_slug.casefold()}
            for alias in [tenant.slug, profile.slug, *(profile.legacy_slugs or [])]:
                normalized = str(alias).casefold().strip()
                if normalized and normalized not in seen:
                    aliases.append(normalized)
                    seen.add(normalized)
            profile.legacy_slugs = aliases[:20]
            tenant.slug = next_slug
            profile.slug = next_slug
        if "contact_email" in request.model_fields_set:
            profile.contact_email = request.contact_email or None
        if request.active is not None:
            profile.publication_status = "PUBLISHED" if request.active else "SUSPENDED"
        if modules_changed:
            session.execute(
                update(MembershipRow)
                .where(
                    MembershipRow.tenant_id == tenant.id,
                    MembershipRow.status.in_(("active", "invited", "suspended")),
                    MembershipRow.deleted_at.is_(None),
                )
                .values(permission_version=MembershipRow.permission_version + 1)
            )
        session.flush()
        _grant_platform_access_to_admin_merchant_staff(
            session,
            context=context,
            tenant=tenant,
        )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "TENANT_SLUG_EXISTS",
            "This storefront path is already in use.",
            kind="conflict",
        ) from exc
    return _summary(session, context=context, tenant=tenant)


def provision_merchant_owner(
    session: Session,
    identity_session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: PlatformMerchantOwnerCreate,
) -> PlatformMerchantOwnerAccount:
    """Create the single, password-login OWNER account for a merchant.

    Tenant creation intentionally stays independent from identity provisioning:
    a recoverable identity-provider failure must not discard the merchant's
    storefront or its product workspace.  The UI surfaces this endpoint both
    during initial setup and as a repair action for legacy merchants.
    """

    _require_platform_admin(context)
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")
    if tenant.status != "active":
        raise ApplicationError(
            "TENANT_NOT_ACTIVE",
            "A merchant must be active before its main account can be opened.",
            kind="conflict",
        )

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

    # The application connection has tenant-scoped access to memberships and
    # roles; the identity connection intentionally does not.  Reading the
    # owner here keeps the identity role from crossing that privilege boundary.
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        existing_owner = repository.get_tenant_owner_account(session, tenant.id)
    if existing_owner is not None:
        existing_membership, _existing_user = existing_owner
        if existing_membership.status in {"active", "suspended"}:
            raise ApplicationError(
                "MERCHANT_OWNER_ALREADY_CONFIGURED",
                "This merchant already has a main account.",
                kind="conflict",
            )

    normalized_identifier = request.login_identifier.casefold()
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        identifier_in_use = session.scalar(
            select(MembershipRow.id).where(
                MembershipRow.tenant_id == tenant.id,
                MembershipRow.login_identifier == normalized_identifier,
            )
        )
    if identifier_in_use is not None:
        raise ApplicationError(
            "MERCHANT_OWNER_IDENTIFIER_CONFLICT",
            "This login account is already used by a member of the merchant.",
            kind="conflict",
        )

    try:
        provisioned = provision_password_identity(
            identity_session,
            identifier=request.login_identifier,
            password=password,
            display_name=request.display_name,
            email=request.email,
        )
    except PasswordIdentityProvisioningError as exc:
        if exc.reason == "identifier_conflict":
            raise ApplicationError(
                "MERCHANT_OWNER_IDENTIFIER_CONFLICT",
                "This login account is already in use.",
                kind="conflict",
            ) from exc
        if exc.reason == "provider_unavailable":
            raise ApplicationError(
                "AUTH_PROVIDER_UNAVAILABLE",
                "The configured identity provider cannot create merchant accounts.",
                kind="unavailable",
            ) from exc
        raise ApplicationError(
            "MERCHANT_OWNER_PROVISIONING_FAILED",
            "The merchant account could not be created. Check the account and try again.",
            kind="conflict",
        ) from exc

    # PostgreSQL production uses the constrained function below: `atc_auth`
    # can create an identity only through a narrowly audited owner-provisioning
    # path, while SQLite keeps the direct local-demo implementation.
    if identity_session.bind is not None and identity_session.bind.dialect.name == "postgresql":
        try:
            row = identity_session.execute(
                text(
                    """
                    SELECT *
                    FROM public.atc_provision_tenant_owner(
                        :actor_user_id,
                        :tenant_id,
                        :user_id,
                        :membership_id,
                        :email,
                        :display_name,
                        :identity_provider,
                        :identity_subject,
                        :login_identifier
                    )
                    """
                ),
                {
                    "actor_user_id": context.user_id,
                    "tenant_id": tenant.id,
                    "user_id": provisioned.user.id,
                    "membership_id": uuid4(),
                    "email": provisioned.user.email_normalized,
                    "display_name": provisioned.user.display_name,
                    "identity_provider": provisioned.user.identity_provider,
                    "identity_subject": provisioned.user.identity_subject,
                    "login_identifier": normalized_identifier,
                },
            ).mappings().one()
            identity_session.commit()
        except DBAPIError as exc:
            identity_session.rollback()
            message = str(exc.orig).casefold()
            if "already has a main account" in message:
                code = "MERCHANT_OWNER_ALREADY_CONFIGURED"
                safe = "This merchant already has a main account."
            elif "login account is already used" in message or "identity already exists" in message:
                code = "MERCHANT_OWNER_IDENTIFIER_CONFLICT"
                safe = "This login account is already in use."
            elif "tenant role is unavailable" in message:
                code = "MERCHANT_OWNER_ROLE_UNAVAILABLE"
                safe = "The merchant owner role is unavailable."
            elif "tenant must be active" in message:
                code = "TENANT_NOT_ACTIVE"
                safe = "A merchant must be active before its main account can be opened."
            else:
                code = "MERCHANT_OWNER_PROVISIONING_FAILED"
                safe = "The merchant account could not be created. Check the account and try again."
            raise ApplicationError(code, safe, kind="conflict") from exc
        _grant_platform_access_to_admin_merchant_staff(
            session,
            context=context,
            tenant=tenant,
        )
        session.commit()
        return PlatformMerchantOwnerAccount(
            user_id=row["owner_user_id"],
            membership_id=row["owner_membership_id"],
            display_name=row["owner_display_name"],
            login_identifier=row["owner_login_identifier"],
            email=row["owner_email"],
            status=row["owner_membership_status"],
            created_at=row["owner_created_at"],
        )

    roles = ensure_tenant_rbac(identity_session, tenant_id=tenant.id)
    owner_role = roles.get("OWNER")
    if owner_role is None:
        raise ApplicationError(
            "MERCHANT_OWNER_ROLE_UNAVAILABLE",
            "The merchant owner role is unavailable.",
            kind="conflict",
        )
    if existing_owner is not None:
        # A legacy pending invitation cannot sign in with a password. Retire
        # it before replacing it with the direct-login owner in local mode.
        existing_owner[0].status = "removed"
    user = provisioned.user
    if normalized_merchant_identity(tenant.identity_code) == "ADMIN":
        user.is_platform_admin = True
    membership = MembershipRow(
        tenant_id=tenant.id,
        user_id=user.id,
        account_scope="STAFF",
        login_identifier=normalized_identifier,
        status="active",
        joined_at=utcnow(),
    )
    identity_session.add(user)
    identity_session.add(membership)
    try:
        identity_session.flush()
        identity_session.add(
            MembershipRoleRow(
                tenant_id=tenant.id,
                membership_id=membership.id,
                role_id=owner_role.id,
                assigned_by_user_id=context.user_id,
            )
        )
        if provisioned.local_credential is not None:
            salt, password_hash = provisioned.local_credential
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
            "MERCHANT_OWNER_IDENTIFIER_CONFLICT",
            "This login account is already in use.",
            kind="conflict",
        ) from exc
    return _owner_account_summary(membership, user)


def reset_merchant_owner_password(
    session: Session,
    identity_session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: PlatformMerchantOwnerPasswordReset,
) -> PlatformMerchantOwnerPasswordResetResponse:
    """Reset an existing merchant owner password and return it once."""

    _require_platform_admin(context)
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")

    password = request.password.get_secret_value()
    if not password_is_valid(
        password=password,
        identifier="merchant-owner",
        display_name=tenant.name,
    ):
        raise ApplicationError(
            "PASSWORD_POLICY_VIOLATION",
            "Password must be exactly 6 digits.",
            kind="invalid",
        )

    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        owner = repository.get_tenant_owner_account(session, tenant.id)
    if owner is None:
        raise ApplicationError(
            "MERCHANT_OWNER_NOT_CONFIGURED",
            "This merchant does not have a main account yet.",
            kind="conflict",
        )

    membership, user = owner
    try:
        reset_password_for_user(
            identity_session,
            user_id=user.id,
            new_password=password,
        )
    except AuthError as exc:
        kind = (
            "unavailable"
            if exc.status_code >= 500
            else "invalid"
            if exc.status_code == 422
            else "not_found"
            if exc.status_code == 404
            else "conflict"
        )
        raise ApplicationError(exc.code, exc.message, kind=kind) from exc
    except Exception:
        identity_session.rollback()
        raise ApplicationError(
            "PASSWORD_RESET_FAILED",
            "The merchant password could not be reset. Please try again.",
            kind="unavailable",
        )

    account = _owner_account_summary(membership, user)
    return PlatformMerchantOwnerPasswordResetResponse(
        account=account,
        one_time_password=password,
    )


def invite_tenant_member(
    session: Session,
    identity_session: Session,
    *,
    context: RequestContext,
    tenant_id: UUID,
    request: PlatformMemberInvitationCreate,
) -> PlatformMemberInvitation:
    _require_platform_admin(context)
    tenant = repository.get_tenant(session, tenant_id)
    if tenant is None:
        raise ApplicationError("TENANT_NOT_FOUND", "Tenant was not found.", kind="not_found")
    if tenant.status != "active":
        raise ApplicationError(
            "TENANT_NOT_ACTIVE",
            "Members can only be invited to an active tenant.",
            kind="conflict",
        )

    # Older tenants may predate automatic role provisioning. Repairing the
    # approved system catalogue is idempotent and remains tenant-scoped.
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        ensure_tenant_rbac(session, tenant_id=tenant.id)
    session.commit()

    result = create_member_invitation(
        identity_session,
        actor_user_id=context.user_id,
        tenant_id=tenant.id,
        email=request.email,
        display_name=request.display_name,
        role_code=request.role,
    )
    return PlatformMemberInvitation(
        tenant_id=tenant.id,
        user_id=result.user_id,
        membership_id=result.membership_id,
        email=result.email,
        display_name=result.display_name,
        role=result.role,  # type: ignore[arg-type]
        membership_status=result.membership_status,  # type: ignore[arg-type]
        created=result.created,
        identity_already_bound=result.identity_already_bound,
        requires_identity_provider_provisioning=not result.identity_already_bound,
    )
