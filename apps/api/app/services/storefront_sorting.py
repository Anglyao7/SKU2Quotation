"""One ranking plan shared by the storefront and its account-scoped editor."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from ..catalog_merchandising import POPULAR_CATEGORY_CODE
from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..product_supplier_models import ProductCategoryRow, ProductRow
from ..public_catalog_models import TenantPublicProfileRow
from ..repositories import public_catalog_repository as catalog
from .subaccount_pricing import subaccount_price_rules
from .subaccount_storefront import account_profile, own_membership, require_manage_storefront, settings_row

AUTO_HOT_LIMIT = 20


@dataclass
class RankingPlan:
    manual_ids: list[UUID]
    hot_ids: list[UUID]
    hot_candidates: set[UUID]
    category_ids: list[UUID]
    excluded_product_ids: set[UUID]

    @property
    def priority_ids(self):
        return list(dict.fromkeys([*self.manual_ids, *self.hot_ids]))


def priority_categories(session, *, tenant_id, config):
    if "priority_category_ids" in config:
        return list(dict.fromkeys(UUID(value) for value in config["priority_category_ids"]))
    # Preserve the old SYSTEM-HOT category preference until explicitly edited.
    return list(session.scalars(select(ProductCategoryRow.id).where(
        ProductCategoryRow.tenant_id == tenant_id,
        ProductCategoryRow.code == POPULAR_CATEGORY_CODE,
        ProductCategoryRow.status == "ACTIVE",
        ProductCategoryRow.deleted_at.is_(None),
    ).order_by(ProductCategoryRow.sort_order, ProductCategoryRow.id)))


def ranking_plan(session, *, tenant_id, profile, membership_id=None):
    config = dict(getattr(profile, "storefront_sorting_config", None) or {})
    hidden = subaccount_price_rules(session, tenant_id=tenant_id, membership_id=membership_id, product_ids=set())[2] if membership_id else set()
    if membership_id:
        from .subaccount_storefront import pinned_product_ids
        manual = sorted(pinned_product_ids(session, tenant_id=tenant_id, membership_id=membership_id), key=str)
    else:
        manual = list(session.scalars(select(ProductRow.id).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.storefront_pinned_at.is_not(None),
            ProductRow.status == "ACTIVE", ProductRow.deleted_at.is_(None),
        ).order_by(ProductRow.storefront_pinned_at.desc(), ProductRow.id)))
    candidates = catalog.hot_product_candidates(
        session, tenant_id=tenant_id, now=utcnow(), excluded_product_ids=hidden, limit=AUTO_HOT_LIMIT,
    ) if profile.hot_products_enabled else []
    opted_out = {UUID(value) for value in config.get("excluded_hot_product_ids", [])}
    return RankingPlan(
        manual_ids=[value for value in manual if value not in hidden],
        hot_ids=[value for value in candidates if value not in opted_out],
        hot_candidates=set(candidates),
        category_ids=priority_categories(session, tenant_id=tenant_id, config=config),
        excluded_product_ids=hidden,
    )


def editor_profile(session, context):
    require_manage_storefront(context)
    profile = session.get(TenantPublicProfileRow, context.tenant_id)
    if profile is None:
        raise ApplicationError("STOREFRONT_NOT_PUBLISHED", "请先配置商品前台。", kind="conflict")
    if context.account_scope == "CUSTOMER_SUBACCOUNT":
        profile = account_profile(session, profile, own_membership(session, context))
    return profile


def editor_settings(session, context):
    profile = editor_profile(session, context)
    categories = session.scalars(select(ProductCategoryRow).where(
        ProductCategoryRow.tenant_id == context.tenant_id,
        ProductCategoryRow.status == "ACTIVE", ProductCategoryRow.deleted_at.is_(None),
    ).order_by(ProductCategoryRow.path, ProductCategoryRow.name, ProductCategoryRow.id)).all()
    available = {row.id for row in categories}
    priorities = priority_categories(session, tenant_id=context.tenant_id, config=dict(profile.storefront_sorting_config or {}))
    return {
        "hot_products_enabled": bool(profile.hot_products_enabled),
        "auto_hot_limit": AUTO_HOT_LIMIT,
        "priority_category_ids": [value for value in priorities if value in available],
        "categories": [{"id": row.id, "name": row.name, "path": row.path or row.name} for row in categories],
    }


def update_categories(session, context, category_ids):
    require_manage_storefront(context)
    requested = list(dict.fromkeys(category_ids))
    available = set(session.scalars(select(ProductCategoryRow.id).where(
        ProductCategoryRow.tenant_id == context.tenant_id, ProductCategoryRow.id.in_(requested),
        ProductCategoryRow.status == "ACTIVE", ProductCategoryRow.deleted_at.is_(None),
    )))
    if set(requested) - available:
        raise ApplicationError("STOREFRONT_CATEGORY_UNAVAILABLE", "分类不存在或已停用，请刷新后重试。", kind="conflict")
    if context.account_scope == "CUSTOMER_SUBACCOUNT":
        row = settings_row(session, own_membership(session, context), create=True)
        settings = dict(row.settings or {})
        config = dict(settings.get("storefront_sorting_config") or {})
        config["priority_category_ids"] = [str(value) for value in requested]
        row.settings = {**settings, "storefront_sorting_config": config}
    else:
        profile = session.scalar(select(TenantPublicProfileRow).where(TenantPublicProfileRow.tenant_id == context.tenant_id).with_for_update().execution_options(populate_existing=True))
        if profile is None:
            raise ApplicationError("STOREFRONT_NOT_PUBLISHED", "请先配置商品前台。", kind="conflict")
        profile.storefront_sorting_config = {**(profile.storefront_sorting_config or {}), "priority_category_ids": [str(value) for value in requested]}
    session.commit()
    return editor_settings(session, context)


def record_hot_override(session, *, tenant_id, product_ids, pinned):
    profile = session.scalar(select(TenantPublicProfileRow).where(TenantPublicProfileRow.tenant_id == tenant_id).with_for_update().execution_options(populate_existing=True))
    if profile is None:
        return False
    config = dict(profile.storefront_sorting_config or {})
    before = set(config.get("excluded_hot_product_ids", []))
    requested = {str(value) for value in product_ids}
    after = before - requested if pinned else before | requested
    if before == after:
        return False
    config["excluded_hot_product_ids"] = sorted(after)
    profile.storefront_sorting_config = config
    return True


def editor_products(session, context, *, query, page, page_size):
    from ..use_cases.public_catalog import _public_image_url

    profile = editor_profile(session, context)
    membership_id = context.membership_id if context.account_scope == "CUSTOMER_SUBACCOUNT" else None
    plan = ranking_plan(session, tenant_id=context.tenant_id, profile=profile, membership_id=membership_id)
    arguments = dict(tenant_id=context.tenant_id, now=utcnow(), query=query, category=None, tags=set(), excluded_product_ids=plan.excluded_product_ids)
    total = catalog.count_public_catalog_products(session, **arguments)
    ids = catalog.list_public_product_ids_page(session, **arguments, page=page, page_size=page_size,
        priority_product_order=plan.priority_ids, priority_category_ids=plan.category_ids)
    rows = session.execute(select(ProductRow, ProductCategoryRow).outerjoin(ProductCategoryRow,
        (ProductCategoryRow.tenant_id == ProductRow.tenant_id) & (ProductCategoryRow.id == ProductRow.category_id)
    ).where(ProductRow.tenant_id == context.tenant_id, ProductRow.id.in_(ids))).all()
    images = catalog.approved_image_map(session, tenant_id=context.tenant_id, product_ids=set(ids))
    by_id = {product.id: (product, category) for product, category in rows}
    manual = set(plan.manual_ids)
    hot = set(plan.hot_ids)
    return {"items": [{
        "id": product_id, "name": by_id[product_id][0].name,
        "product_code": by_id[product_id][0].product_code,
        "category": (by_id[product_id][1].path or by_id[product_id][1].name) if by_id[product_id][1] else None,
        "image_url": _public_image_url(images.get(product_id), slug=profile.slug),
        "is_prioritized": product_id in manual or product_id in hot,
        "priority_source": "MANUAL" if product_id in manual else "HOT" if product_id in hot else None,
        "is_hot_candidate": product_id in plan.hot_candidates,
    } for product_id in ids], "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size}
