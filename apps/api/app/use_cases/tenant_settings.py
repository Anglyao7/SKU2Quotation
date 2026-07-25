from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_schemas import MerchantSettingsResponse, MerchantSettingsUpdate
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories.public_catalog_repository import find_published_profile_by_slug
from ..services.auth.dependencies import RequestContext
from ..tenant_slugs import storefront_slug_from_name


def _require_settings_permission(context: RequestContext) -> None:
    if "system.settings_manage" not in context.permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            "You do not have permission to manage merchant settings.",
            kind="forbidden",
        )


def _response(tenant: TenantRow) -> MerchantSettingsResponse:
    return MerchantSettingsResponse(
        name=tenant.name,
        slug=tenant.slug,
        storefront_path=f"/{tenant.slug}",
    )


def get_merchant_settings(
    session: Session, *, context: RequestContext
) -> MerchantSettingsResponse:
    tenant = session.scalar(
        select(TenantRow).where(
            TenantRow.id == context.tenant_id,
            TenantRow.deleted_at.is_(None),
        )
    )
    if tenant is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND", "Merchant workspace was not found.", kind="not_found"
        )
    return _response(tenant)


def update_merchant_settings(
    session: Session,
    *,
    context: RequestContext,
    request: MerchantSettingsUpdate,
) -> MerchantSettingsResponse:
    _require_settings_permission(context)
    tenant = session.scalar(
        select(TenantRow).where(
            TenantRow.id == context.tenant_id,
            TenantRow.deleted_at.is_(None),
        )
    )
    if tenant is None:
        raise ApplicationError(
            "TENANT_NOT_FOUND", "Merchant workspace was not found.", kind="not_found"
        )
    try:
        new_slug = storefront_slug_from_name(request.name)
    except ValueError as exc:
        raise ApplicationError(
            "MERCHANT_NAME_INVALID",
            "Merchant name must contain at least one letter or number.",
        ) from exc

    slug_owner = session.scalar(
        select(TenantRow).where(
            TenantRow.slug == new_slug,
            TenantRow.id != tenant.id,
            TenantRow.deleted_at.is_(None),
        )
    )
    public_owner = find_published_profile_by_slug(session, slug=new_slug)
    if slug_owner is not None or (
        public_owner is not None and public_owner.tenant_id != tenant.id
    ):
        raise ApplicationError(
            "STOREFRONT_PATH_EXISTS",
            "A merchant with the same storefront path already exists.",
            kind="conflict",
        )

    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant.id,
            TenantPublicProfileRow.deleted_at.is_(None),
        )
    )
    if profile is None:
        profile = TenantPublicProfileRow(
            tenant_id=tenant.id,
            slug=tenant.slug,
            publication_status="PUBLISHED" if tenant.status == "active" else "SUSPENDED",
        )
        session.add(profile)
        session.flush()

    if new_slug != tenant.slug:
        aliases: list[str] = []
        seen = {new_slug.casefold()}
        for alias in [tenant.slug, profile.slug, *(profile.legacy_slugs or [])]:
            normalized = str(alias).casefold().strip()
            if normalized and normalized not in seen:
                aliases.append(normalized)
                seen.add(normalized)
        profile.legacy_slugs = aliases[:20]
        tenant.slug = new_slug
        profile.slug = new_slug
    tenant.name = request.name

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "STOREFRONT_PATH_EXISTS",
            "A merchant with the same storefront path already exists.",
            kind="conflict",
        ) from exc
    return _response(tenant)
