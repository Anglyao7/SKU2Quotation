"""Account-scoped storefront presentation without granting merchant-wide settings access."""
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..identity_models import MembershipRow, UserRow
from ..public_catalog_models import SubaccountStorefrontProfileRow
from .auth.dependencies import RequestContext


def can_manage_storefront(context: RequestContext) -> bool:
    if context.account_scope == "CUSTOMER_SUBACCOUNT":
        return "customer_portal.access" in context.permissions
    return "system.settings_manage" in context.permissions


def require_manage_storefront(context: RequestContext) -> None:
    if not can_manage_storefront(context):
        raise ApplicationError("PERMISSION_REQUIRED", "You cannot manage this storefront.", kind="forbidden")


def own_membership(session: Session, context: RequestContext) -> MembershipRow:
    require_manage_storefront(context)
    row = session.scalar(select(MembershipRow).where(
        MembershipRow.id == context.membership_id,
        MembershipRow.tenant_id == context.tenant_id,
        MembershipRow.user_id == context.user_id,
        MembershipRow.account_scope == "CUSTOMER_SUBACCOUNT",
        MembershipRow.status == "active",
        MembershipRow.deleted_at.is_(None),
    ))
    if row is None or not row.storefront_slug:
        raise ApplicationError("STOREFRONT_ACCOUNT_NOT_FOUND", "Account storefront was not found.", kind="not_found")
    return row


def settings_row(session: Session, membership: MembershipRow, *, create: bool = False):
    # Serialize independent tab saves through the existing account row, including
    # concurrent first saves before the presentation row has been created.
    if create:
        session.execute(select(MembershipRow.id).where(
            MembershipRow.id == membership.id, MembershipRow.tenant_id == membership.tenant_id,
        ).with_for_update()).one()
    row = session.scalar(select(SubaccountStorefrontProfileRow).where(
        SubaccountStorefrontProfileRow.tenant_id == membership.tenant_id,
        SubaccountStorefrontProfileRow.membership_id == membership.id,
    ).execution_options(populate_existing=True))
    if row is None and create:
        row = SubaccountStorefrontProfileRow(
            tenant_id=membership.tenant_id, membership_id=membership.id, settings={},
        )
        session.add(row)
    return row


def account_profile(session: Session, profile, membership: MembershipRow, *, user=None):
    row = settings_row(session, membership)
    config = dict(row.settings or {}) if row is not None else {}
    if user is None:
        user = session.get(UserRow, membership.user_id)
    # Deliberately do not inherit branding, links, contact details or HTML pages.
    return SimpleNamespace(
        tenant_id=membership.tenant_id,
        slug=membership.storefront_slug,
        name=config.get("name") or getattr(user, "display_name", None) or membership.login_identifier or membership.storefront_slug,
        description=config.get("description"),
        logo_url=None,
        logo_object_key=config.get("logo_object_key"),
        updated_at=row.updated_at if row is not None else None,
        contact_email=None, contact_phone=None,
        storefront_locales=config.get("storefront_locales", getattr(profile, "storefront_locales", ["zh-CN"])),
        storefront_default_locale=config.get("storefront_default_locale", getattr(profile, "storefront_default_locale", "zh-CN")),
        hot_products_enabled=config.get("hot_products_enabled", False),
        category_showcase_enabled=True,
        storefront_exchange_rates_enabled=config.get("storefront_exchange_rates_enabled", False),
        storefront_category_layout_mode=config.get("storefront_category_layout_mode", getattr(profile, "storefront_category_layout_mode", "AUTO")),
        storefront_footer_config=config.get("storefront_footer_config", {"sections": []}),
        storefront_sorting_config=config.get("storefront_sorting_config"),
        all_products_position=0, ai_search_questions=[], popular_search_terms=[],
        support_widget_config={},
        owner_membership_id=membership.id,
    )


def public_account_profile(session: Session, profile, *, slug: str):
    membership = session.info.get("public_storefront_account")
    if membership is None and profile.slug.casefold() == slug.casefold().strip():
        return profile
    if membership is None:
        membership = session.scalar(select(MembershipRow).where(
            MembershipRow.tenant_id == profile.tenant_id,
            MembershipRow.storefront_slug == slug.casefold().strip(),
            MembershipRow.account_scope == "CUSTOMER_SUBACCOUNT",
            MembershipRow.status == "active",
            MembershipRow.deleted_at.is_(None),
        ))
    if membership is None:
        return profile
    if membership.tenant_id != profile.tenant_id:
        raise ApplicationError("STOREFRONT_ACCOUNT_TENANT_MISMATCH", "Account storefront was not found.", kind="not_found")
    return account_profile(session, profile, membership)


def pinned_product_ids(session: Session, *, tenant_id, membership_id) -> set[UUID]:
    config = session.scalar(select(SubaccountStorefrontProfileRow.settings).where(
        SubaccountStorefrontProfileRow.tenant_id == tenant_id,
        SubaccountStorefrontProfileRow.membership_id == membership_id,
    )) or {}
    return {UUID(value) for value in config.get("pinned_product_ids", [])}


def update_pinned_products(session: Session, *, context: RequestContext, product_ids, pinned: bool):
    from ..product_supplier_models import ProductRow
    from .subaccount_pricing import subaccount_price_rules

    membership = own_membership(session, context)
    row = settings_row(session, membership, create=True)
    config = dict(row.settings or {})
    requested = set(product_ids)
    hidden = subaccount_price_rules(session, tenant_id=context.tenant_id, membership_id=membership.id, product_ids=requested)[2]
    valid = set(session.scalars(select(ProductRow.id).where(
        ProductRow.tenant_id == context.tenant_id, ProductRow.id.in_(requested),
        ProductRow.status == "ACTIVE", ProductRow.deleted_at.is_(None),
    ))) - hidden
    current = set(config.get("pinned_product_ids", []))
    valid_strings = {str(value) for value in valid}
    updated = current | valid_strings if pinned else current - valid_strings
    config["pinned_product_ids"] = sorted(updated)
    sorting = dict(config.get("storefront_sorting_config") or {})
    excluded = set(sorting.get("excluded_hot_product_ids", []))
    sorting["excluded_hot_product_ids"] = sorted(excluded - valid_strings if pinned else excluded | valid_strings)
    config["storefront_sorting_config"] = sorting
    row.settings = config
    session.commit()
    return {
        "success_count": len(valid), "failed_count": len(requested - valid), "total_count": len(requested),
        "failed_items": [{"product_id": str(value), "reason": "商品不可用"} for value in requested - valid],
        "affected_product_count": len(current ^ updated),
    }
