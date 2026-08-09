from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import (
    LocalAccountCredentialRow,
    MembershipRoleRow,
    MembershipRow,
    TenantSubscriptionRow,
    TenantRow,
    UserRow,
)
from ..model_mixins import utcnow
from ..platform_admin_schemas import (
    PlatformMemberInvitation,
    PlatformMemberInvitationCreate,
    PlatformMerchantOwnerAccount,
    PlatformMerchantOwnerCreate,
    PlatformTenantCreate,
    PlatformTenantSubscriptionUpdate,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import platform_admin_repository as repository
from ..saas_seed import ensure_tenant_rbac
from ..inventory_seed import ensure_default_warehouse
from ..services.auth.dependencies import RequestContext
from ..services.member_invitations import invite_tenant_member as create_member_invitation
from ..services.storefront_paths import (
    allocate_storefront_slug,
    exact_storefront_slug_is_available,
)
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
from ..tenant_modules import normalized_tenant_modules
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
        enabled_modules=list(normalized_tenant_modules(tenant.enabled_modules)),
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


def create_tenant(
    session: Session,
    *,
    context: RequestContext,
    request: PlatformTenantCreate,
) -> PlatformTenantSummary:
    _require_platform_admin(context)
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
    tenant = TenantRow(
        organization_id=context.organization_id,
        name=request.name,
        slug=slug,
        default_locale=request.default_locale,
        default_currency=request.default_currency,
        timezone=request.timezone,
        enabled_modules=list(request.enabled_modules),
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
    if request.active is False and tenant.id == context.tenant_id:
        raise ApplicationError(
            "ACTIVE_TENANT_SUSPENSION_FORBIDDEN",
            "Switch to another active workspace before suspending this tenant.",
            kind="conflict",
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
    modules_changed = False
    if "enabled_modules" in request.model_fields_set:
        if request.enabled_modules is None:
            raise ApplicationError(
                "TENANT_MODULES_REQUIRED",
                "Enabled modules must be a list.",
                kind="invalid",
            )
        requested_modules = list(request.enabled_modules or [])
        modules_changed = requested_modules != list(
            normalized_tenant_modules(tenant.enabled_modules)
        )
        tenant.enabled_modules = requested_modules
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
            "Password must be 8-128 characters and include both letters and numbers.",
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
