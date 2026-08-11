from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.orm import Session

from ..catalog_share_schemas import CatalogShareCreate, CatalogShareResponse
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..public_catalog_models import CatalogShareRow
from ..repositories import catalog_share_repository as repository
from ..repositories import public_catalog_repository
from ..services.storefront_branding import storefront_logo_url


@dataclass(frozen=True)
class CatalogShareConstraint:
    target_type: str
    product_ids: tuple[UUID, ...] = ()
    category_path: str | None = None


def _require_permission(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission {code} is required.",
            kind="forbidden",
        )


def _published_store(session: Session, *, tenant_id: UUID):
    tenant = public_catalog_repository.get_active_tenant(
        session, tenant_id=tenant_id
    )
    profile = public_catalog_repository.find_published_profile_by_tenant(
        session, tenant_id=tenant_id
    )
    if tenant is None or profile is None:
        raise ApplicationError(
            "STOREFRONT_NOT_PUBLISHED",
            "请先发布商家前台，再创建分享链接。",
            kind="conflict",
        )
    return tenant, profile


def _public_store(session: Session, *, slug: str):
    profile = public_catalog_repository.find_published_profile_by_slug(
        session, slug=slug.casefold().strip()
    )
    if profile is None:
        raise ApplicationError(
            "CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found"
        )
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = public_catalog_repository.get_active_tenant(
        session, tenant_id=profile.tenant_id
    )
    if tenant is None:
        raise ApplicationError(
            "CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found"
        )
    return tenant, profile


def _category_name(session: Session, row: CatalogShareRow) -> str | None:
    if row.category_id is None:
        return None
    category = repository.get_category(
        session, tenant_id=row.tenant_id, category_id=row.category_id
    )
    return category.name if category is not None else None


def _response(
    session: Session,
    *,
    row: CatalogShareRow,
    store_name: str,
    store_slug: str,
    store_subtitle: str | None,
    store_logo_url: str | None,
) -> CatalogShareResponse:
    response_category_path = row.category_path
    if row.target_type == "CATEGORY":
        current_category = (
            repository.get_category(
                session, tenant_id=row.tenant_id, category_id=row.category_id
            )
            if row.category_id is not None
            else None
        )
        current_category_path = (
            (current_category.path or current_category.name).strip()
            if current_category is not None
            else row.category_path
        )
        response_category_path = current_category_path
        current_item_count = public_catalog_repository.count_public_catalog_products(
            session,
            tenant_id=row.tenant_id,
            now=utcnow(),
            query="",
            category=current_category_path,
            tags=set(),
        )
    else:
        current_item_count = public_catalog_repository.count_public_catalog_products(
            session,
            tenant_id=row.tenant_id,
            now=utcnow(),
            query="",
            category=None,
            tags=set(),
            product_ids={UUID(str(value)) for value in row.product_ids},
        )
    return CatalogShareResponse(
        id=row.id,
        token=row.share_token,
        target_type=row.target_type,
        title=row.title,
        item_count=current_item_count,
        category_id=row.category_id,
        category_name=_category_name(session, row),
        category_path=response_category_path,
        share_path=f"/{store_slug}/share/{row.id.hex}",
        store_name=store_name,
        store_subtitle=(store_subtitle or "").strip() or None,
        store_logo_url=store_logo_url,
        logo_position=row.logo_position,
        created_at=row.created_at,
    )


def create_share(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    request: CatalogShareCreate,
) -> CatalogShareResponse:
    _require_permission(permissions, "catalog.publish")
    tenant, profile = _published_store(session, tenant_id=tenant_id)
    logo_url = storefront_logo_url(profile)
    if request.logo_position != "NONE" and not logo_url:
        raise ApplicationError(
            "CATALOG_SHARE_LOGO_REQUIRED",
            "请先上传商家 Logo，再选择名片 Logo 位置。",
            kind="conflict",
        )
    now = utcnow()
    product_ids: list[UUID] = []
    category_id: UUID | None = None
    category_path: str | None = None

    if request.target_type == "PRODUCTS":
        sku_rows = repository.list_skus(
            session, tenant_id=tenant_id, sku_ids=request.sku_ids
        )
        found_sku_ids = {row.id for row in sku_rows}
        if found_sku_ids != set(request.sku_ids):
            raise ApplicationError(
                "CATALOG_SHARE_SKU_NOT_FOUND",
                "部分已选 SKU 不存在，请刷新商品库后重试。",
                kind="not_found",
            )
        sku_by_id = {row.id: row for row in sku_rows}
        product_ids = list(
            dict.fromkeys(sku_by_id[sku_id].product_id for sku_id in request.sku_ids)
        )
        public_rows = public_catalog_repository.list_public_catalog_rows_by_product_ids(
            session,
            tenant_id=tenant_id,
            product_ids=product_ids,
            now=now,
            category=None,
        )
        public_product_ids = {row[2].id for row in public_rows}
        if public_product_ids != set(product_ids):
            raise ApplicationError(
                "CATALOG_SHARE_PRODUCT_NOT_PUBLIC",
                "部分商品尚未上架，无法加入公开分享。",
                kind="conflict",
            )
        products = repository.list_products(
            session, tenant_id=tenant_id, product_ids=product_ids
        )
        product_by_id = {row.id: row for row in products}
        title = (
            product_by_id[product_ids[0]].name
            if len(product_ids) == 1
            else f"{len(product_ids)} 件商品精选"
        )
        fingerprint_source = "PRODUCTS:" + ",".join(
            sorted(str(product_id) for product_id in product_ids)
        )
        item_count = len(product_ids)
    else:
        category_id = request.category_id
        assert category_id is not None
        category = repository.get_category(
            session, tenant_id=tenant_id, category_id=category_id
        )
        if category is None or category.status != "ACTIVE":
            raise ApplicationError(
                "CATALOG_SHARE_CATEGORY_NOT_FOUND",
                "分类不存在或未启用。",
                kind="not_found",
            )
        category_path = (category.path or category.name).strip()
        item_count = public_catalog_repository.count_public_catalog_products(
            session,
            tenant_id=tenant_id,
            now=now,
            query="",
            category=category_path,
            tags=set(),
        )
        if item_count <= 0:
            raise ApplicationError(
                "CATALOG_SHARE_CATEGORY_EMPTY",
                "该分类暂时没有已上架商品。",
                kind="conflict",
            )
        title = category.name
        fingerprint_source = f"CATEGORY:{category_id}"

    if request.logo_position != "NONE":
        fingerprint_source = f"{fingerprint_source}:LOGO:{request.logo_position}"
    fingerprint = sha256(fingerprint_source.encode("utf-8")).hexdigest()
    existing = repository.find_by_fingerprint(
        session, tenant_id=tenant_id, fingerprint=fingerprint
    )
    if existing is not None:
        return _response(
            session,
            row=existing,
            store_name=tenant.name,
            store_slug=profile.slug,
            store_subtitle=profile.description,
            store_logo_url=logo_url,
        )

    token = ""
    for _ in range(8):
        candidate = token_urlsafe(12)
        if repository.find_by_token(
            session, tenant_id=tenant_id, token=candidate
        ) is None:
            token = candidate
            break
    if not token:
        raise ApplicationError(
            "CATALOG_SHARE_TOKEN_FAILED",
            "暂时无法生成分享链接，请稍后重试。",
            kind="internal",
        )

    row = repository.add(
        session,
        CatalogShareRow(
            tenant_id=tenant_id,
            share_token=token,
            target_type=request.target_type,
            product_ids=[str(product_id) for product_id in product_ids],
            category_id=category_id,
            category_path=category_path,
            title=title,
            item_count=item_count,
            logo_position=request.logo_position,
            fingerprint=fingerprint,
            created_by_user_id=user_id,
        ),
    )
    session.commit()
    session.refresh(row)
    return _response(
        session,
        row=row,
        store_name=tenant.name,
        store_slug=profile.slug,
        store_subtitle=profile.description,
        store_logo_url=logo_url,
    )


def resolve_share(
    session: Session, *, slug: str, token: str
) -> CatalogShareResponse:
    tenant, profile = _public_store(session, slug=slug)
    row = repository.find_by_token(
        session, tenant_id=tenant.id, token=token.strip()
    )
    if row is None:
        raise ApplicationError(
            "CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found"
        )
    return _response(
        session,
        row=row,
        store_name=tenant.name,
        store_slug=profile.slug,
        store_subtitle=profile.description,
        store_logo_url=storefront_logo_url(profile),
    )


def resolve_share_constraint(
    session: Session, *, tenant_id: UUID, token: str
) -> CatalogShareConstraint:
    row = repository.find_by_token(
        session, tenant_id=tenant_id, token=token.strip()
    )
    if row is None:
        raise ApplicationError(
            "CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found"
        )
    if row.target_type == "CATEGORY":
        category = (
            repository.get_category(
                session, tenant_id=tenant_id, category_id=row.category_id
            )
            if row.category_id is not None
            else None
        )
        return CatalogShareConstraint(
            target_type=row.target_type,
            category_path=(
                (category.path or category.name).strip()
                if category is not None
                else row.category_path
            ),
        )
    try:
        product_ids = tuple(UUID(str(value)) for value in row.product_ids)
    except (TypeError, ValueError) as exc:
        raise ApplicationError(
            "CATALOG_SHARE_NOT_FOUND", "分享内容不存在或已失效。", kind="not_found"
        ) from exc
    return CatalogShareConstraint(
        target_type=row.target_type,
        product_ids=product_ids,
    )
