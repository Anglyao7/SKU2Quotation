from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..tag_models import ProductTagRow


_UNSET = object()


def get_or_create_tags(
    session: Session,
    *,
    tenant_id: UUID,
    tag_names: list[str],
) -> list[ProductTagRow]:
    """获取或创建标签，返回标签行对象"""
    if not tag_names:
        return []

    # 规范化标签名称
    normalized_map = {tag.strip().casefold(): tag.strip() for tag in tag_names if tag.strip()}
    if not normalized_map:
        return []

    # 查询已存在的标签
    existing_tags = session.execute(
        select(ProductTagRow)
        .where(
            ProductTagRow.tenant_id == tenant_id,
            ProductTagRow.normalized_name.in_(list(normalized_map.keys())),
        )
    ).scalars().all()

    existing_normalized = {tag.normalized_name for tag in existing_tags}
    result = list(existing_tags)

    # 创建不存在的标签
    new_tags = []
    for normalized, display_name in normalized_map.items():
        if normalized not in existing_normalized:
            new_tag = ProductTagRow(
                id=uuid4(),
                tenant_id=tenant_id,
                name=display_name,
                normalized_name=normalized,
                usage_count=0,
            )
            new_tags.append(new_tag)
            result.append(new_tag)

    if new_tags:
        session.add_all(new_tags)
        session.flush()

    return result


def increment_tag_usage(
    session: Session,
    *,
    tenant_id: UUID,
    tag_names: list[str],
) -> None:
    """增加标签使用计数"""
    if not tag_names:
        return

    normalized_names = [tag.strip().casefold() for tag in tag_names if tag.strip()]
    if not normalized_names:
        return

    session.execute(
        select(ProductTagRow)
        .where(
            ProductTagRow.tenant_id == tenant_id,
            ProductTagRow.normalized_name.in_(normalized_names),
        )
        .with_for_update()
    )

    # 批量更新使用次数
    from sqlalchemy import update
    session.execute(
        update(ProductTagRow)
        .where(
            ProductTagRow.tenant_id == tenant_id,
            ProductTagRow.normalized_name.in_(normalized_names),
        )
        .values(usage_count=ProductTagRow.usage_count + 1)
    )


def list_tags(
    session: Session,
    *,
    tenant_id: UUID,
    category: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[ProductTagRow], int]:
    """列出标签，支持按分类筛选"""
    query = select(ProductTagRow).where(ProductTagRow.tenant_id == tenant_id)

    if category:
        query = query.where(ProductTagRow.category == category)

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = session.execute(count_query).scalar() or 0

    # 按使用次数和名称排序
    query = (
        query.order_by(ProductTagRow.usage_count.desc(), ProductTagRow.name)
        .limit(limit)
        .offset(offset)
    )

    tags = session.execute(query).scalars().all()
    return list(tags), total


def update_tag(
    session: Session,
    *,
    tag_id: UUID,
    tenant_id: UUID,
    name: str | None | object = _UNSET,
    description: str | None | object = _UNSET,
    category: str | None | object = _UNSET,
) -> ProductTagRow | None:
    """更新标签信息"""
    tag = session.get(ProductTagRow, tag_id)
    if not tag or tag.tenant_id != tenant_id:
        return None

    if isinstance(name, str) and name.strip():
        display_name = name.strip()
        normalized = display_name.casefold()

        # 检查是否与其他标签冲突
        existing = session.execute(
            select(ProductTagRow).where(
                ProductTagRow.tenant_id == tenant_id,
                ProductTagRow.normalized_name == normalized,
                ProductTagRow.id != tag_id,
            )
        ).scalar_one_or_none()

        if existing:
            raise ValueError(f"标签 '{display_name}' 已存在")

        tag.name = display_name
        tag.normalized_name = normalized

    if description is not _UNSET:
        tag.description = (
            description.strip()
            if isinstance(description, str) and description.strip()
            else None
        )

    if category is not _UNSET:
        tag.category = (
            category.strip()
            if isinstance(category, str) and category.strip()
            else None
        )

    session.flush()
    return tag


def delete_tag(
    session: Session,
    *,
    tag_id: UUID,
    tenant_id: UUID,
) -> bool:
    """删除标签"""
    tag = session.get(ProductTagRow, tag_id)
    if not tag or tag.tenant_id != tenant_id:
        return False

    session.delete(tag)
    session.flush()
    return True
