from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import set_request_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..platform_admin_schemas import (
    PlatformMemberInvitation,
    PlatformMemberInvitationCreate,
    PlatformTenantCreate,
    PlatformTenantSummary,
    PlatformTenantUpdate,
)
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import platform_admin_repository as repository
from ..saas_seed import ensure_tenant_rbac
from ..services.auth.dependencies import RequestContext
from ..services.member_invitations import invite_tenant_member as create_member_invitation
from ..tenant_slugs import is_reserved_tenant_slug


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
        contact_email=profile.contact_email if profile else None,
        sku_count=sku_count,
        quote_count=quote_count,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
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
    slug = request.slug.lower()
    if is_reserved_tenant_slug(slug):
        raise ApplicationError(
            "TENANT_SLUG_RESERVED",
            "This storefront slug is reserved by the platform.",
            kind="invalid",
        )
    if repository.find_tenant_by_slug(session, slug) is not None:
        raise ApplicationError(
            "TENANT_SLUG_EXISTS",
            "This storefront slug is already in use.",
            kind="conflict",
        )
    tenant = TenantRow(
        organization_id=context.organization_id,
        name=request.name,
        slug=slug,
        default_locale=request.default_locale,
        default_currency=request.default_currency,
        timezone=request.timezone,
        status="active" if request.active else "suspended",
    )
    session.add(tenant)
    try:
        session.flush()
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
        tenant.name = request.name
    if request.active is not None:
        tenant.status = "active" if request.active else "suspended"
    with _tenant_scope(session, context=context, tenant_id=tenant.id):
        profile = repository.get_public_profile(session, tenant.id)
        if profile is None:
            profile = TenantPublicProfileRow(
                tenant_id=tenant.id,
                slug=tenant.slug,
                publication_status="PUBLISHED" if tenant.status == "active" else "SUSPENDED",
            )
            session.add(profile)
        if "contact_email" in request.model_fields_set:
            profile.contact_email = request.contact_email or None
        if request.active is not None:
            profile.publication_status = "PUBLISHED" if request.active else "SUSPENDED"
        session.flush()
    session.commit()
    return _summary(session, context=context, tenant=tenant)


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
