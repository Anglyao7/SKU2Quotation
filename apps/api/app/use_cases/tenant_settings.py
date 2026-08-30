from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..auth_schemas import MerchantSettingsResponse, MerchantSettingsUpdate
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..inventory_models import WarehouseRow
from ..public_catalog_models import TenantPublicProfileRow
from ..services.auth.dependencies import RequestContext
from ..services.storefront_branding import (
    MAX_MERCHANT_LOGO_BYTES,
    InvalidStorefrontLogo,
    normalize_storefront_logo,
    storefront_logo_url,
)
from ..services.storefront_paths import allocate_storefront_slug
from ..storefront_footer import storefront_footer_config, storefront_footer_sections
from ..storefront_locales import (
    effective_storefront_locales,
    normalize_storefront_locale,
)
from ..tenant_slugs import storefront_slug_from_name


def _require_settings_permission(context: RequestContext) -> None:
    if "system.settings_manage" not in context.permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            "You do not have permission to manage merchant settings.",
            kind="forbidden",
        )


def _response(
    tenant: TenantRow,
    profile: TenantPublicProfileRow | None,
) -> MerchantSettingsResponse:
    storefront_locales = effective_storefront_locales(
        profile.storefront_locales if profile is not None else None,
        source_locale=tenant.default_locale,
    )
    storefront_default_locale = (
        normalize_storefront_locale(
            profile.storefront_default_locale if profile is not None else None
        )
        or normalize_storefront_locale(tenant.default_locale)
        or "zh-CN"
    )
    if storefront_default_locale not in storefront_locales:
        storefront_default_locale = storefront_locales[0]
    return MerchantSettingsResponse(
        name=tenant.name,
        slug=tenant.slug,
        storefront_path=f"/{tenant.slug}",
        logo_url=storefront_logo_url(profile),
        share_card_subtitle=(profile.description or "").strip() or None
        if profile is not None
        else None,
        business_mode=(
            "DOMESTIC" if tenant.default_currency.upper() == "CNY" else "EXPORT"
        ),
        default_currency=tenant.default_currency.upper(),
        storefront_locales=storefront_locales,
        storefront_default_locale=storefront_default_locale,
        hot_products_enabled=(
            bool(profile.hot_products_enabled) if profile is not None else False
        ),
        storefront_footer_sections=storefront_footer_sections(
            profile.storefront_footer_config if profile is not None else None,
            merchant_name=tenant.name,
            contact_email=profile.contact_email if profile is not None else None,
        ),
    )


def _activate_currency_warehouse(
    session: Session,
    *,
    tenant: TenantRow,
    context: RequestContext,
    currency: str,
) -> None:
    """Select a valuation-safe default warehouse for the display currency.

    Existing warehouse balances and documents keep their original currency.
    When no warehouse exists for the new mode, a clean warehouse is created
    instead of relabelling historical inventory values.
    """

    currency = currency.strip().upper()
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
            if warehouse.status == "ACTIVE"
            and warehouse.currency.upper() == currency
        ),
        None,
    )
    for warehouse in warehouses:
        if warehouse.is_default and warehouse is not target:
            warehouse.is_default = False
            warehouse.version += 1
    session.flush()

    if target is None:
        base_code = (
            "MAIN"
            if currency == "CNY"
            else "EXPORT"
            if currency == "USD"
            else f"FX-{currency}"
        )
        used_codes = {warehouse.code.casefold() for warehouse in warehouses}
        code = base_code
        suffix = 2
        while code.casefold() in used_codes:
            code = f"{base_code}-{suffix}"
            suffix += 1
        target = WarehouseRow(
            tenant_id=tenant.id,
            code=code,
            name=(
                "默认仓库"
                if currency == "CNY"
                else "外贸仓"
                if currency == "USD"
                else f"{currency} 仓库"
            ),
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
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant.id,
            TenantPublicProfileRow.deleted_at.is_(None),
        )
    )
    return _response(tenant, profile)


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
    profile = session.scalar(
        select(TenantPublicProfileRow).where(
            TenantPublicProfileRow.tenant_id == tenant.id,
            TenantPublicProfileRow.deleted_at.is_(None),
        )
    )
    if profile is None and (
        request.name is not None
        or request.share_card_subtitle is not None
        or request.storefront_locales is not None
        or request.storefront_default_locale is not None
        or request.hot_products_enabled is not None
        or request.storefront_footer_sections is not None
    ):
        profile = TenantPublicProfileRow(
            tenant_id=tenant.id,
            slug=tenant.slug,
            publication_status=(
                "PUBLISHED" if tenant.status == "active" else "SUSPENDED"
            ),
        )
        session.add(profile)
        session.flush()
    if request.name is not None:
        try:
            base_slug = storefront_slug_from_name(request.name)
        except ValueError as exc:
            raise ApplicationError(
                "MERCHANT_NAME_INVALID",
                "Merchant name must contain at least one letter or number.",
            ) from exc
        new_slug = allocate_storefront_slug(
            session,
            base=base_slug,
            exclude_tenant_id=tenant.id,
        )

        assert profile is not None

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

    if request.storefront_locales is not None:
        assert profile is not None
        profile.storefront_locales = effective_storefront_locales(
            request.storefront_locales,
            source_locale=tenant.default_locale,
        )
        current_default = normalize_storefront_locale(
            profile.storefront_default_locale
        )
        if current_default not in profile.storefront_locales:
            profile.storefront_default_locale = (
                normalize_storefront_locale(tenant.default_locale)
                or profile.storefront_locales[0]
            )

    if request.storefront_default_locale is not None:
        assert profile is not None
        enabled_locales = effective_storefront_locales(
            profile.storefront_locales,
            source_locale=tenant.default_locale,
        )
        requested_default = normalize_storefront_locale(
            request.storefront_default_locale
        )
        if requested_default is None or requested_default not in enabled_locales:
            raise ApplicationError(
                "STOREFRONT_DEFAULT_LOCALE_DISABLED",
                "默认语言必须是已启用的前台语言。",
            )
        profile.storefront_default_locale = requested_default

    if request.share_card_subtitle is not None:
        assert profile is not None
        profile.description = request.share_card_subtitle or None

    if request.hot_products_enabled is not None:
        assert profile is not None
        profile.hot_products_enabled = request.hot_products_enabled

    if request.storefront_footer_sections is not None:
        assert profile is not None
        profile.storefront_footer_config = storefront_footer_config(
            request.storefront_footer_sections
        )

    requested_currency = request.default_currency
    if request.business_mode is not None:
        mode_currency = "USD" if request.business_mode == "EXPORT" else "CNY"
        if requested_currency is not None and requested_currency != mode_currency:
            raise ApplicationError(
                "MERCHANT_CURRENCY_CONFLICT",
                "Business mode and default currency do not match.",
            )
        requested_currency = mode_currency
    if requested_currency is not None:
        _activate_currency_warehouse(
            session,
            tenant=tenant,
            context=context,
            currency=requested_currency,
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
    return _response(tenant, profile)


def upload_merchant_logo(
    session: Session,
    *,
    context: RequestContext,
    content: bytes,
) -> MerchantSettingsResponse:
    _require_settings_permission(context)
    if not content:
        raise ApplicationError("MERCHANT_LOGO_EMPTY", "请选择一张 Logo 图片。")
    if len(content) > MAX_MERCHANT_LOGO_BYTES:
        raise ApplicationError(
            "MERCHANT_LOGO_TOO_LARGE",
            f"Logo 图片不能超过 {MAX_MERCHANT_LOGO_BYTES // (1024 * 1024)} MB。",
            kind="too_large",
        )

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

    try:
        normalized = normalize_storefront_logo(content)
    except InvalidStorefrontLogo as exc:
        raise ApplicationError(
            "MERCHANT_LOGO_INVALID",
            "Logo 无法识别，请上传 PNG、JPG 或 WebP 图片。",
        ) from exc

    storage = get_object_storage()
    object_key = f"tenants/{tenant.id}/branding/logo/{uuid4().hex}.webp"
    try:
        with tempfile.NamedTemporaryFile(suffix=".webp") as temporary:
            temporary.write(normalized)
            temporary.flush()
            storage.put_file(
                Path(temporary.name),
                object_key=object_key,
                content_type="image/webp",
            )
    except Exception as exc:
        raise ApplicationError(
            "MERCHANT_LOGO_STORAGE_UNAVAILABLE",
            "Logo 上传到对象存储失败，请稍后重试。",
            kind="unavailable",
        ) from exc

    previous_object_key = (profile.logo_object_key or "").strip() or None
    profile.logo_object_key = object_key
    profile.logo_url = None
    try:
        session.commit()
        session.refresh(profile)
    except Exception:
        session.rollback()
        try:
            storage.delete(object_key)
        except Exception:
            pass
        raise

    if previous_object_key and previous_object_key != object_key:
        try:
            storage.delete(previous_object_key)
        except Exception:
            # The current logo is already durable; stale-object cleanup is best effort.
            pass
    return _response(tenant, profile)
