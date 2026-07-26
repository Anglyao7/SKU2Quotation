from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..services import tag_service
from ..services.auth.dependencies import (
    RequestContext,
    current_context,
    get_authenticated_session,
)

router = APIRouter(prefix="/api/tags", tags=["标签管理"])


def _context(session: Session):
    return current_context(session)


def _require_any(context: RequestContext, *permissions: str) -> None:
    if any(permission in context.permissions for permission in permissions):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "PERMISSION_DENIED",
            "message": f"One of these permissions is required: {', '.join(permissions)}",
        },
    )


class TagResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    category: str | None
    usage_count: int
    created_at: str
    updated_at: str


class TagListResponse(BaseModel):
    tags: list[TagResponse]
    total: int
    limit: int
    offset: int


class CreateTagRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="标签名称")
    description: str | None = Field(None, max_length=500, description="标签说明")
    category: str | None = Field(None, max_length=50, description="标签分类")


class UpdateTagRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80, description="标签名称")
    description: str | None = Field(None, max_length=500, description="标签说明")
    category: str | None = Field(None, max_length=50, description="标签分类")


def _tag_to_response(tag) -> TagResponse:
    return TagResponse(
        id=tag.id,
        name=tag.name,
        description=tag.description,
        category=tag.category,
        usage_count=tag.usage_count,
        created_at=tag.created_at.isoformat(),
        updated_at=tag.updated_at.isoformat(),
    )


@router.get("", response_model=TagListResponse)
def list_tags(
    session: Session = Depends(get_authenticated_session),
    category: str | None = Query(None, description="按分类筛选"),
    limit: int = Query(200, ge=1, le=500, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
) -> TagListResponse:
    """列出所有标签"""
    context = _context(session)
    _require_any(context, "product.view", "product.edit")
    tags, total = tag_service.list_tags(
        session,
        tenant_id=context.tenant_id,
        category=category,
        limit=limit,
        offset=offset,
    )
    return TagListResponse(
        tags=[_tag_to_response(tag) for tag in tags],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TagResponse, status_code=201)
def create_tag(
    session: Session = Depends(get_authenticated_session),
    payload: CreateTagRequest = ...,
) -> TagResponse:
    """创建新标签"""
    context = _context(session)
    _require_any(context, "product.edit")
    try:
        tags = tag_service.get_or_create_tags(
            session,
            tenant_id=context.tenant_id,
            tag_names=[payload.name],
        )
        if not tags:
            raise HTTPException(status_code=400, detail="标签名称无效")

        tag = tags[0]

        # 更新描述和分类
        if payload.description or payload.category:
            tag = tag_service.update_tag(
                session,
                tag_id=tag.id,
                tenant_id=context.tenant_id,
                description=payload.description,
                category=payload.category,
            )

        session.commit()
        return _tag_to_response(tag)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{tag_id}", response_model=TagResponse)
def update_tag(
    tag_id: UUID,
    session: Session = Depends(get_authenticated_session),
    payload: UpdateTagRequest = ...,
) -> TagResponse:
    """更新标签"""
    context = _context(session)
    _require_any(context, "product.edit")
    try:
        changes = payload.model_dump(exclude_unset=True)
        tag = tag_service.update_tag(
            session,
            tag_id=tag_id,
            tenant_id=context.tenant_id,
            **changes,
        )
        if not tag:
            raise HTTPException(status_code=404, detail="标签不存在")

        session.commit()
        return _tag_to_response(tag)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{tag_id}", status_code=204)
def delete_tag(
    tag_id: UUID,
    session: Session = Depends(get_authenticated_session),
) -> None:
    """删除标签"""
    context = _context(session)
    _require_any(context, "product.edit")
    success = tag_service.delete_tag(
        session,
        tag_id=tag_id,
        tenant_id=context.tenant_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="标签不存在")

    session.commit()
