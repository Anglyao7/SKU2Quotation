from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..database import set_public_tenant_context
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..repositories import public_catalog_repository
from ..services.auth.dependencies import RequestContext
from ..storefront_page_models import StorefrontCustomPageRow
from ..storefront_page_schemas import (
    MAX_STOREFRONT_CUSTOM_PAGES,
    MAX_STOREFRONT_HTML_BYTES,
    PublicStorefrontPageDocument,
    PublicStorefrontPageLink,
    StorefrontCustomPageListResponse,
    StorefrontCustomPageResponse,
    StorefrontCustomPageUpdate,
    normalize_storefront_page_slug,
)

_HTML_TAG_PATTERN = re.compile(r"<[A-Za-z][^>]*>")
logger = logging.getLogger(__name__)


def _require_manage(context: RequestContext) -> None:
    if "system.settings_manage" not in context.permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            "You do not have permission to manage storefront pages.",
            kind="forbidden",
        )


def _page_response(row: StorefrontCustomPageRow) -> StorefrontCustomPageResponse:
    return StorefrontCustomPageResponse(
        id=row.id,
        title=row.title,
        slug=row.slug,
        path=f"/pages/{row.slug}",
        enabled=row.enabled,
        exchange_rates_enabled=row.exchange_rates_enabled,
        sort_order=row.sort_order,
        original_filename=row.original_filename,
        byte_size=row.byte_size,
        content_sha256=row.content_sha256,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _tenant_page(
    session: Session,
    *,
    tenant_id: UUID,
    page_id: UUID,
) -> StorefrontCustomPageRow:
    row = session.scalar(
        select(StorefrontCustomPageRow).where(
            StorefrontCustomPageRow.tenant_id == tenant_id,
            StorefrontCustomPageRow.id == page_id,
            StorefrontCustomPageRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError(
            "STOREFRONT_PAGE_NOT_FOUND",
            "前台自定义页面不存在。",
            kind="not_found",
        )
    return row


def _validated_html(content: bytes, *, filename: str) -> str:
    normalized_filename = Path(filename or "").name
    if Path(normalized_filename).suffix.casefold() != ".html":
        raise ApplicationError(
            "STOREFRONT_PAGE_FILE_TYPE_INVALID",
            "这里只接受单个 .html 文件。",
            kind="validation",
        )
    if not content:
        raise ApplicationError(
            "STOREFRONT_PAGE_FILE_EMPTY",
            "上传的 HTML 文件不能为空。",
            kind="validation",
        )
    if len(content) > MAX_STOREFRONT_HTML_BYTES:
        raise ApplicationError(
            "STOREFRONT_PAGE_FILE_TOO_LARGE",
            f"HTML 文件不能超过 {MAX_STOREFRONT_HTML_BYTES // (1024 * 1024)} MB。",
            kind="too_large",
        )
    try:
        html = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApplicationError(
            "STOREFRONT_PAGE_ENCODING_INVALID",
            "HTML 文件必须使用 UTF-8 编码。",
            kind="validation",
        ) from exc
    if "\x00" in html or not _HTML_TAG_PATTERN.search(html):
        raise ApplicationError(
            "STOREFRONT_PAGE_HTML_INVALID",
            "文件中没有可识别的 HTML 页面内容。",
            kind="validation",
        )
    return html


def _store_html(content: bytes, *, tenant_id: UUID, page_id: UUID) -> str:
    object_key = f"tenants/{tenant_id}/storefront/pages/{page_id}/{uuid4().hex}.html"
    descriptor, raw_path = tempfile.mkstemp(prefix="atc-storefront-page-", suffix=".html")
    path = Path(raw_path)
    try:
        with open(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
        get_object_storage().put_file(
            path,
            object_key=object_key,
            content_type="text/html; charset=utf-8",
        )
    finally:
        path.unlink(missing_ok=True)
    return object_key


def list_pages(
    session: Session,
    *,
    context: RequestContext,
) -> StorefrontCustomPageListResponse:
    _require_manage(context)
    rows = list(
        session.scalars(
            select(StorefrontCustomPageRow)
            .where(
                StorefrontCustomPageRow.tenant_id == context.tenant_id,
                StorefrontCustomPageRow.deleted_at.is_(None),
            )
            .order_by(
                StorefrontCustomPageRow.sort_order,
                StorefrontCustomPageRow.created_at,
                StorefrontCustomPageRow.id,
            )
        ).all()
    )
    return StorefrontCustomPageListResponse(
        items=[_page_response(row) for row in rows],
        total=len(rows),
    )


def create_page(
    session: Session,
    *,
    context: RequestContext,
    title: str,
    slug: str,
    filename: str,
    content: bytes,
) -> StorefrontCustomPageResponse:
    _require_manage(context)
    normalized_title = title.strip()
    if not normalized_title or len(normalized_title) > 80:
        raise ApplicationError(
            "STOREFRONT_PAGE_TITLE_INVALID",
            "导航名称长度需要在 1 到 80 个字符之间。",
            kind="validation",
        )
    try:
        normalized_slug = normalize_storefront_page_slug(slug)
    except ValueError as exc:
        raise ApplicationError(
            "STOREFRONT_PAGE_SLUG_INVALID",
            "路由只可使用小写英文字母、数字和连字符。",
            kind="validation",
        ) from exc
    _validated_html(content, filename=filename)
    count = session.scalar(
        select(func.count(StorefrontCustomPageRow.id)).where(
            StorefrontCustomPageRow.tenant_id == context.tenant_id,
            StorefrontCustomPageRow.deleted_at.is_(None),
        )
    )
    if int(count or 0) >= MAX_STOREFRONT_CUSTOM_PAGES:
        raise ApplicationError(
            "STOREFRONT_PAGE_LIMIT_REACHED",
            f"每个商家最多可以添加 {MAX_STOREFRONT_CUSTOM_PAGES} 个自定义页面。",
            kind="conflict",
        )
    duplicate = session.scalar(
        select(StorefrontCustomPageRow.id).where(
            StorefrontCustomPageRow.tenant_id == context.tenant_id,
            StorefrontCustomPageRow.slug == normalized_slug,
        )
    )
    if duplicate is not None:
        raise ApplicationError(
            "STOREFRONT_PAGE_SLUG_EXISTS",
            "这个路由已经被当前商家使用。",
            kind="conflict",
        )
    max_order = session.scalar(
        select(func.max(StorefrontCustomPageRow.sort_order)).where(
            StorefrontCustomPageRow.tenant_id == context.tenant_id,
            StorefrontCustomPageRow.deleted_at.is_(None),
        )
    )
    page_id = uuid4()
    object_key = _store_html(content, tenant_id=context.tenant_id, page_id=page_id)
    row = StorefrontCustomPageRow(
        id=page_id,
        tenant_id=context.tenant_id,
        title=normalized_title,
        slug=normalized_slug,
        object_key=object_key,
        original_filename=Path(filename).name[:500],
        content_sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
        enabled=True,
        exchange_rates_enabled=False,
        sort_order=(int(max_order) + 1) if max_order is not None else 0,
        version=1,
        created_by_user_id=context.user_id,
        updated_by_user_id=context.user_id,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        get_object_storage().delete(object_key)
        raise ApplicationError(
            "STOREFRONT_PAGE_SLUG_EXISTS",
            "这个路由已经被当前商家使用。",
            kind="conflict",
        ) from exc
    session.refresh(row)
    return _page_response(row)


def update_page(
    session: Session,
    *,
    context: RequestContext,
    page_id: UUID,
    request: StorefrontCustomPageUpdate,
) -> StorefrontCustomPageResponse:
    _require_manage(context)
    row = _tenant_page(session, tenant_id=context.tenant_id, page_id=page_id)
    if row.version != request.expected_version:
        raise ApplicationError(
            "STOREFRONT_PAGE_VERSION_CONFLICT",
            "页面配置已被更新，请刷新后重试。",
            kind="conflict",
        )
    if request.title is not None:
        row.title = request.title
    if request.slug is not None:
        row.slug = request.slug
    if request.enabled is not None:
        row.enabled = request.enabled
    if request.exchange_rates_enabled is not None:
        row.exchange_rates_enabled = request.exchange_rates_enabled
    if request.sort_order is not None:
        row.sort_order = request.sort_order
    row.updated_by_user_id = context.user_id
    row.version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "STOREFRONT_PAGE_SLUG_EXISTS",
            "这个路由已经被当前商家使用。",
            kind="conflict",
        ) from exc
    session.refresh(row)
    return _page_response(row)


def replace_page_html(
    session: Session,
    *,
    context: RequestContext,
    page_id: UUID,
    expected_version: int,
    filename: str,
    content: bytes,
) -> StorefrontCustomPageResponse:
    _require_manage(context)
    _validated_html(content, filename=filename)
    row = _tenant_page(session, tenant_id=context.tenant_id, page_id=page_id)
    if row.version != expected_version:
        raise ApplicationError(
            "STOREFRONT_PAGE_VERSION_CONFLICT",
            "页面内容已被更新，请刷新后重试。",
            kind="conflict",
        )
    old_object_key = row.object_key
    new_object_key = _store_html(content, tenant_id=context.tenant_id, page_id=row.id)
    row.object_key = new_object_key
    row.original_filename = Path(filename).name[:500]
    row.content_sha256 = hashlib.sha256(content).hexdigest()
    row.byte_size = len(content)
    row.updated_by_user_id = context.user_id
    row.version += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        get_object_storage().delete(new_object_key)
        raise
    session.refresh(row)
    try:
        get_object_storage().delete(old_object_key)
    except Exception as exc:  # noqa: BLE001 - replacement already committed
        logger.warning(
            "failed to delete replaced storefront page object %s: %s",
            old_object_key,
            exc,
        )
    return _page_response(row)


def delete_page(
    session: Session,
    *,
    context: RequestContext,
    page_id: UUID,
) -> None:
    _require_manage(context)
    row = _tenant_page(session, tenant_id=context.tenant_id, page_id=page_id)
    object_key = row.object_key
    session.delete(row)
    session.commit()
    try:
        get_object_storage().delete(object_key)
    except Exception as exc:  # noqa: BLE001 - database deletion is authoritative
        logger.warning(
            "failed to delete storefront page object %s: %s",
            object_key,
            exc,
        )


def public_navigation_pages(
    session: Session,
    *,
    tenant_id: UUID,
    tenant_slug: str,
) -> list[PublicStorefrontPageLink]:
    rows = list(
        session.scalars(
            select(StorefrontCustomPageRow)
            .where(
                StorefrontCustomPageRow.tenant_id == tenant_id,
                StorefrontCustomPageRow.deleted_at.is_(None),
                StorefrontCustomPageRow.enabled.is_(True),
            )
            .order_by(
                StorefrontCustomPageRow.sort_order,
                StorefrontCustomPageRow.created_at,
                StorefrontCustomPageRow.id,
            )
        ).all()
    )
    prefix = f"/{tenant_slug}/pages"
    return [
        PublicStorefrontPageLink(
            title=row.title,
            slug=row.slug,
            path=f"{prefix}/{row.slug}",
            exchange_rates_enabled=row.exchange_rates_enabled,
        )
        for row in rows
    ]


def public_page(
    session: Session,
    *,
    tenant_slug: str,
    page_slug: str,
) -> PublicStorefrontPageDocument:
    normalized_store_slug = tenant_slug.casefold().strip()
    profile = public_catalog_repository.find_published_profile_by_slug(
        session,
        slug=normalized_store_slug,
    )
    if profile is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    set_public_tenant_context(session, tenant_id=profile.tenant_id)
    tenant = session.scalar(
        select(TenantRow).where(
            TenantRow.id == profile.tenant_id,
            TenantRow.deleted_at.is_(None),
            TenantRow.status == "active",
        )
    )
    if tenant is None:
        raise ApplicationError(
            "STORE_NOT_FOUND",
            "Store was not found.",
            kind="not_found",
        )
    try:
        normalized_page_slug = normalize_storefront_page_slug(page_slug)
    except ValueError as exc:
        raise ApplicationError(
            "STOREFRONT_PAGE_NOT_FOUND",
            "前台页面不存在。",
            kind="not_found",
        ) from exc
    row = session.scalar(
        select(StorefrontCustomPageRow).where(
            StorefrontCustomPageRow.tenant_id == tenant.id,
            StorefrontCustomPageRow.slug == normalized_page_slug,
            StorefrontCustomPageRow.enabled.is_(True),
            StorefrontCustomPageRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApplicationError(
            "STOREFRONT_PAGE_NOT_FOUND",
            "前台页面不存在。",
            kind="not_found",
        )
    try:
        with get_object_storage().materialize(row.object_key) as path:
            content = path.read_bytes()
        html = content.decode("utf-8-sig")
    except Exception as exc:
        raise ApplicationError(
            "STOREFRONT_PAGE_CONTENT_UNAVAILABLE",
            "页面内容暂时无法读取。",
            kind="unavailable",
        ) from exc
    return PublicStorefrontPageDocument(
        title=row.title,
        slug=row.slug,
        exchange_rates_enabled=row.exchange_rates_enabled,
        html=html,
        content_sha256=row.content_sha256,
        updated_at=row.updated_at,
    )
