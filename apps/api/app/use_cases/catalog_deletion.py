from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog_operation_models import CatalogDeleteJobRow
from ..database import SessionLocal, set_request_context
from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..product_center_schemas import ProductDeleteAllJobResponse
from .product_center import delete_all_products


logger = logging.getLogger(__name__)
_delete_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="catalog-delete",
)
_stale_job_after = timedelta(minutes=30)


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_REQUIRED",
            f"Permission required: {code}",
            kind="forbidden",
        )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _job_response(job: CatalogDeleteJobRow) -> ProductDeleteAllJobResponse:
    return ProductDeleteAllJobResponse(
        id=job.id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        total_products=job.total_products,
        total_skus=job.total_skus,
        deleted_product_count=job.deleted_product_count,
        deleted_sku_count=job.deleted_sku_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _active_job(session: Session, *, tenant_id: UUID) -> CatalogDeleteJobRow | None:
    return session.scalar(
        select(CatalogDeleteJobRow)
        .where(
            CatalogDeleteJobRow.tenant_id == tenant_id,
            CatalogDeleteJobRow.status.in_(("QUEUED", "RUNNING")),
        )
        .order_by(CatalogDeleteJobRow.created_at.desc())
        .limit(1)
    )


def _expire_stale_job(session: Session, *, tenant_id: UUID) -> None:
    active = _active_job(session, tenant_id=tenant_id)
    if active is None:
        return
    if _as_utc(active.updated_at) >= utcnow() - _stale_job_after:
        return
    active.status = "FAILED"
    active.stage = "FAILED"
    active.error_message = "删除任务因服务中断而停止，请重新发起。"
    active.completed_at = utcnow()
    session.commit()


def get_catalog_delete_job(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: UUID,
) -> ProductDeleteAllJobResponse:
    _require(permissions, "product.edit")
    _expire_stale_job(session, tenant_id=tenant_id)
    job = session.scalar(
        select(CatalogDeleteJobRow).where(
            CatalogDeleteJobRow.tenant_id == tenant_id,
            CatalogDeleteJobRow.id == job_id,
        )
    )
    if job is None:
        raise ApplicationError(
            "CATALOG_DELETE_JOB_NOT_FOUND",
            "全部商品删除任务不存在。",
            kind="not_found",
        )
    return _job_response(job)


def _finish_job(
    *,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    job_id: UUID,
    result: dict[str, int] | None = None,
    error_message: str | None = None,
) -> None:
    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        values: dict[str, object] = {
            "status": "SUCCEEDED" if result is not None else "FAILED",
            "stage": "COMPLETED" if result is not None else "FAILED",
            "completed_at": utcnow(),
            "updated_at": utcnow(),
            "error_message": error_message,
        }
        if result is not None:
            values.update(
                progress=100,
                total_products=result["deleted_product_count"],
                total_skus=result["deleted_sku_count"],
                deleted_product_count=result["deleted_product_count"],
                deleted_sku_count=result["deleted_sku_count"],
            )
        session.execute(
            update(CatalogDeleteJobRow)
            .where(
                CatalogDeleteJobRow.tenant_id == tenant_id,
                CatalogDeleteJobRow.id == job_id,
                CatalogDeleteJobRow.status == "RUNNING",
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        session.commit()


def _run_catalog_delete_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
) -> None:
    with SessionLocal() as claim_session:
        set_request_context(
            claim_session,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        claimed = claim_session.execute(
            update(CatalogDeleteJobRow)
            .where(
                CatalogDeleteJobRow.tenant_id == tenant_id,
                CatalogDeleteJobRow.id == job_id,
                CatalogDeleteJobRow.status == "QUEUED",
            )
            .values(
                status="RUNNING",
                stage="ARCHIVING_PRODUCTS",
                progress=10,
                started_at=utcnow(),
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        claim_session.commit()
    if claimed != 1:
        return

    try:
        with SessionLocal() as delete_session:
            set_request_context(
                delete_session,
                organization_id=organization_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            result = delete_all_products(
                delete_session,
                tenant_id=tenant_id,
                user_id=user_id,
                membership_id=membership_id,
                permissions=frozenset({"product.edit"}),
            )
        _finish_job(
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
            job_id=job_id,
            result=result,
        )
    except Exception as exc:
        logger.exception("catalog delete job %s failed", job_id)
        safe_message = (
            exc.safe_message
            if isinstance(exc, ApplicationError)
            else "全部商品删除失败，数据未被完整提交，请稍后重试。"
        )
        _finish_job(
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
            job_id=job_id,
            error_message=safe_message,
        )


def _dispatch_catalog_delete_job(
    *,
    job_id: UUID,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
) -> None:
    _delete_executor.submit(
        _run_catalog_delete_job,
        job_id=job_id,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
        membership_id=membership_id,
    )


def start_catalog_delete_job(
    session: Session,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
) -> ProductDeleteAllJobResponse:
    _require(permissions, "product.edit")
    _expire_stale_job(session, tenant_id=tenant_id)
    existing = _active_job(session, tenant_id=tenant_id)
    if existing is not None:
        return _job_response(existing)

    job = CatalogDeleteJobRow(
        tenant_id=tenant_id,
        requested_by_membership_id=membership_id,
        requested_by_user_id=user_id,
        status="QUEUED",
        stage="QUEUED",
        progress=0,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = _active_job(session, tenant_id=tenant_id)
        if existing is not None:
            return _job_response(existing)
        raise ApplicationError(
            "CATALOG_DELETE_BUSY",
            "当前商家已有全部商品删除任务正在执行。",
            kind="conflict",
        ) from exc

    try:
        _dispatch_catalog_delete_job(
            job_id=job.id,
            organization_id=organization_id,
            tenant_id=tenant_id,
            user_id=user_id,
            membership_id=membership_id,
        )
    except RuntimeError as exc:
        job.status = "FAILED"
        job.stage = "FAILED"
        job.error_message = "删除任务暂时无法启动，请稍后重试。"
        job.completed_at = utcnow()
        session.commit()
        raise ApplicationError(
            "CATALOG_DELETE_DISPATCH_FAILED",
            job.error_message,
        ) from exc
    return _job_response(job)
