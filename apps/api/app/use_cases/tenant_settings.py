from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_schemas import MerchantSettingsResponse, MerchantSettingsUpdate
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..inventory_models import WarehouseRow
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
        business_mode=(
            "EXPORT" if tenant.default_currency.upper() == "USD" else "DOMESTIC"
        ),
        default_currency=tenant.default_currency.upper(),
    )


def _activate_mode_warehouse(
    session: Session,
    *,
    tenant: TenantRow,
    context: RequestContext,
    business_mode: str,
) -> None:
    """Select a valuation-safe default warehouse for the requested mode.

    Existing warehouse balances and documents keep their original currency.
    When no warehouse exists for the new mode, a clean warehouse is created
    instead of relabelling historical inventory values.
    """

    currency = "USD" if business_mode == "EXPORT" else "CNY"
    warehouses = list(
        session.scalars(
            select(WarehouseRow).where(
                WarehouseRow.tenant_id == tenant.id,
                WarehouseRow.deleted_at.is_(None),
            )
        ).all()
    )
    target = next(
        (
            warehouse
            for warehouse in warehouses
            if warehouse.status == "ACTIVE" and warehouse.currency == currency
        ),
        None,
    )
    for warehouse in warehouses:
        if warehouse.is_default and warehouse is not target:
            warehouse.is_default = False
            warehouse.version += 1
    session.flush()

    if target is None:
        base_code = "EXPORT" if business_mode == "EXPORT" else "MAIN"
        used_codes = {warehouse.code.casefold() for warehouse in warehouses}
        code = base_code
        suffix = 2
        while code.casefold() in used_codes:
            code = f"{base_code}-{suffix}"
            suffix += 1
        target = WarehouseRow(
            tenant_id=tenant.id,
            code=code,
            name="外贸仓" if business_mode == "EXPORT" else "默认仓库",
            currency=currency,
            status="ACTIVE",
            is_default=True,
            version=1,
            created_by_membership_id=context.membership_id,
        )
        session.add(target)
    elif not target.is_default:
        target.is_default = True
        target.version += 1
    tenant.default_currency = currency


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
    if request.name is not None:
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
                publication_status=(
                    "PUBLISHED" if tenant.status == "active" else "SUSPENDED"
                ),
            )
            session.add(profile)
            session.flush()

        if new_slug != tenant.slug:
            aliases: list[str] = []
            seen = {new_slug.casefold()}
            for alias in [
                tenant.slug,
                profile.slug,
                *(profile.legacy_slugs or []),
            ]:
                normalized = str(alias).casefold().strip()
                if normalized and normalized not in seen:
                    aliases.append(normalized)
                    seen.add(normalized)
            profile.legacy_slugs = aliases[:20]
            tenant.slug = new_slug
            profile.slug = new_slug
        tenant.name = request.name

    if request.business_mode is not None:
        _activate_mode_warehouse(
            session,
            tenant=tenant,
            context=context,
            business_mode=request.business_mode,
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "MERCHANT_SETTINGS_CONFLICT",
            "Merchant settings could not be updated because they conflict.",
            kind="conflict",
        ) from exc
    return _response(tenant)
