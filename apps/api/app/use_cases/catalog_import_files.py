from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..catalog_operation_models import CatalogImportBatchRow
from ..db_models import ImportJobRow
from ..domain.errors import ApplicationError
from ..model_mixins import utcnow
from ..models import CatalogImportFile, CatalogImportFileRollbackResponse
from ..product_center_models import ProductAuditEventRow, SkuRow
from ..product_supplier_models import ProductRow
from ..services.catalog_write_guard import lock_catalog_write
from .product_center import batch_delete_skus


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def _require_catalog_import_access(permissions: frozenset[str]) -> None:
    _require(permissions, "product.import")
    _require(permissions, "product.edit")
    _require(permissions, "catalog.publish")


def _counts_by_source_file(
    session: Session,
    *,
    tenant_id: UUID,
    source_file_ids: list[str],
) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    if not source_file_ids:
        return {}, {}, {}, {}

    product_totals = dict(
        session.execute(
            select(ProductRow.origin_source_file_id, func.count(ProductRow.id))
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.origin_source_file_id.in_(source_file_ids),
            )
            .group_by(ProductRow.origin_source_file_id)
            .execution_options(include_deleted=True)
        ).all()
    )
    product_remaining = dict(
        session.execute(
            select(ProductRow.origin_source_file_id, func.count(ProductRow.id))
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.origin_source_file_id.in_(source_file_ids),
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
            .group_by(ProductRow.origin_source_file_id)
            .execution_options(include_deleted=True)
        ).all()
    )
    sku_totals = dict(
        session.execute(
            select(SkuRow.origin_source_file_id, func.count(SkuRow.id))
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.origin_source_file_id.in_(source_file_ids),
            )
            .group_by(SkuRow.origin_source_file_id)
            .execution_options(include_deleted=True)
        ).all()
    )
    sku_remaining = dict(
        session.execute(
            select(SkuRow.origin_source_file_id, func.count(SkuRow.id))
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.origin_source_file_id.in_(source_file_ids),
                SkuRow.deleted_at.is_(None),
                SkuRow.status != "ARCHIVED",
            )
            .group_by(SkuRow.origin_source_file_id)
            .execution_options(include_deleted=True)
        ).all()
    )
    return (
        {str(key): int(value) for key, value in product_totals.items() if key},
        {str(key): int(value) for key, value in product_remaining.items() if key},
        {str(key): int(value) for key, value in sku_totals.items() if key},
        {str(key): int(value) for key, value in sku_remaining.items() if key},
    )


def _file_status(
    job: ImportJobRow,
    *,
    created_product_count: int,
    created_sku_count: int,
    remaining_product_count: int,
    remaining_sku_count: int,
) -> tuple[str, bool, str | None]:
    if job.file_rollback_at is not None:
        return "REVOKED", False, "这个文件带来的商品已经撤回。"
    if job.status in {"scanning", "parsing"}:
        return "PROCESSING", False, "文件仍在导入，请完成后再撤回。"
    if job.status == "failed":
        return "FAILED", False, "文件导入失败，没有写入可撤回的商品。"
    if remaining_sku_count > 0 or remaining_product_count > 0:
        return "AVAILABLE", True, None
    if created_sku_count > 0 or created_product_count > 0:
        return "NO_REMAINING_ITEMS", False, "这个文件带来的商品已经不存在。"
    return (
        "NO_CREATED_ITEMS",
        False,
        "该文件没有新建商品，或者历史记录无法安全确认文件来源。",
    )


def list_import_files(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[CatalogImportFile]:
    _require_catalog_import_access(permissions)
    jobs = session.scalars(
        select(ImportJobRow)
        .options(selectinload(ImportJobRow.source_file))
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.source_type == "PRODUCT_TEMPLATE",
            ImportJobRow.deleted_at.is_(None),
        )
        .order_by(ImportJobRow.created_at.desc())
        .limit(limit)
    ).all()
    source_file_ids = list(dict.fromkeys(job.source_file_id for job in jobs))
    (
        product_totals,
        product_remaining,
        sku_totals,
        sku_remaining,
    ) = _counts_by_source_file(
        session,
        tenant_id=tenant_id,
        source_file_ids=source_file_ids,
    )

    result: list[CatalogImportFile] = []
    for job in jobs:
        created_product_count = product_totals.get(job.source_file_id, 0)
        remaining_product_count = product_remaining.get(job.source_file_id, 0)
        created_sku_count = sku_totals.get(job.source_file_id, 0)
        remaining_sku_count = sku_remaining.get(job.source_file_id, 0)
        rollback_status, can_rollback, unavailable_reason = _file_status(
            job,
            created_product_count=created_product_count,
            created_sku_count=created_sku_count,
            remaining_product_count=remaining_product_count,
            remaining_sku_count=remaining_sku_count,
        )
        result.append(
            CatalogImportFile(
                source_file_id=job.source_file_id,
                import_job_id=job.id,
                batch_id=job.batch_id,
                filename=job.source_file.original_filename,
                import_status=job.status,
                rollback_status=rollback_status,
                created_product_count=created_product_count,
                created_sku_count=created_sku_count,
                remaining_product_count=remaining_product_count,
                remaining_sku_count=remaining_sku_count,
                created_at=job.created_at.isoformat(),
                completed_at=(
                    job.completed_at.isoformat() if job.completed_at else None
                ),
                rolled_back_at=(
                    job.file_rollback_at.isoformat()
                    if job.file_rollback_at
                    else None
                ),
                can_rollback=can_rollback,
                unavailable_reason=unavailable_reason,
            )
        )
    return result


def _archive_origin_products_without_skus(
    session: Session,
    *,
    tenant_id: UUID,
    source_file_id: str,
    user_id: UUID,
) -> None:
    products = session.scalars(
        select(ProductRow)
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.origin_source_file_id == source_file_id,
            ProductRow.deleted_at.is_(None),
            ProductRow.status != "ARCHIVED",
        )
        .execution_options(include_deleted=True)
        .with_for_update()
    ).all()
    if not products:
        return
    product_ids = [row.id for row in products]
    remaining_by_product = dict(
        session.execute(
            select(SkuRow.product_id, func.count(SkuRow.id))
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.product_id.in_(product_ids),
                SkuRow.deleted_at.is_(None),
                SkuRow.status != "ARCHIVED",
            )
            .group_by(SkuRow.product_id)
        ).all()
    )
    now = utcnow()
    for product in products:
        if remaining_by_product.get(product.id, 0) != 0:
            continue
        product.status = "ARCHIVED"
        product.archived_at = now
        product.current_version += 1
        product.search_document_version = 0
        product.updated_by = user_id
        product.updated_at = now


def _update_batch_status_after_file_rollback(
    session: Session,
    *,
    tenant_id: UUID,
    batch_id: UUID | None,
) -> None:
    if batch_id is None:
        return
    batch = session.scalar(
        select(CatalogImportBatchRow)
        .where(
            CatalogImportBatchRow.tenant_id == tenant_id,
            CatalogImportBatchRow.id == batch_id,
            CatalogImportBatchRow.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if batch is None:
        return
    jobs = session.scalars(
        select(ImportJobRow).where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.batch_id == batch_id,
        )
    ).all()
    completed_or_empty = [
        job for job in jobs if job.status not in {"scanning", "parsing"}
    ]
    revoked_jobs = [job for job in completed_or_empty if job.file_rollback_at]
    settled_jobs = [
        job
        for job in completed_or_empty
        if job.file_rollback_at is not None or job.status == "failed"
    ]
    if completed_or_empty and len(settled_jobs) == len(completed_or_empty):
        batch.status = "REVOKED"
        batch.revoked_at = utcnow()
    elif revoked_jobs:
        batch.status = "PARTIALLY_REVOKED"
        batch.revoked_at = None
    batch.updated_at = utcnow()


def rollback_import_file(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    source_file_id: str,
) -> CatalogImportFileRollbackResponse:
    _require_catalog_import_access(permissions)
    lock_catalog_write(session, tenant_id=tenant_id)
    job = session.scalar(
        select(ImportJobRow)
        .options(selectinload(ImportJobRow.source_file))
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.source_file_id == source_file_id,
            ImportJobRow.source_type == "PRODUCT_TEMPLATE",
            ImportJobRow.deleted_at.is_(None),
        )
        .order_by(ImportJobRow.created_at.desc())
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if job is None:
        raise ApplicationError(
            "IMPORT_FILE_NOT_FOUND",
            "导入文件不存在。",
            kind="not_found",
        )
    if job.status in {"scanning", "parsing"}:
        raise ApplicationError(
            "IMPORT_FILE_STILL_RUNNING",
            "该文件仍在导入，请完成后再撤回。",
            kind="conflict",
        )
    if job.status == "failed":
        raise ApplicationError(
            "IMPORT_FILE_FAILED",
            "该文件导入失败，没有写入可撤回的商品。",
            kind="validation_failed",
        )
    if job.file_rollback_at is not None:
        return CatalogImportFileRollbackResponse(
            source_file_id=source_file_id,
            import_job_id=job.id,
            status="REVOKED",
            deleted_sku_count=0,
            archived_product_count=0,
            retained_product_count=0,
            remaining_sku_count=0,
        )

    source_skus = session.scalars(
        select(SkuRow)
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.origin_source_file_id == source_file_id,
            SkuRow.deleted_at.is_(None),
            SkuRow.status != "ARCHIVED",
        )
        .execution_options(include_deleted=True)
        .with_for_update()
    ).all()
    source_products = session.scalars(
        select(ProductRow)
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.origin_source_file_id == source_file_id,
            ProductRow.deleted_at.is_(None),
            ProductRow.status != "ARCHIVED",
        )
        .execution_options(include_deleted=True)
        .with_for_update()
    ).all()
    if not source_skus and not source_products:
        raise ApplicationError(
            "IMPORT_FILE_PROVENANCE_MISSING",
            "该文件没有可确认来源的商品，无法安全撤回。",
            kind="validation_failed",
        )

    affected_product_ids = list(
        dict.fromkeys(
            [row.product_id for row in source_skus]
            + [row.id for row in source_products]
        )
    )
    active_before = {
        row.id
        for row in session.scalars(
            select(ProductRow)
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id.in_(affected_product_ids),
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
            .execution_options(include_deleted=True)
        ).all()
    }

    deleted_sku_count = 0
    if source_skus:
        deleted = batch_delete_skus(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            membership_id=membership_id,
            permissions=permissions,
            sku_ids=[row.id for row in source_skus],
            commit=False,
            archive_empty_product_ids={row.id for row in source_products},
        )
        deleted_sku_count = int(deleted["success_count"])
    _archive_origin_products_without_skus(
        session,
        tenant_id=tenant_id,
        source_file_id=source_file_id,
        user_id=user_id,
    )
    session.flush()

    active_after = {
        row.id
        for row in session.scalars(
            select(ProductRow)
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id.in_(affected_product_ids),
                ProductRow.deleted_at.is_(None),
                ProductRow.status != "ARCHIVED",
            )
            .execution_options(include_deleted=True)
        ).all()
    }
    archived_product_count = len(active_before - active_after)
    retained_product_count = len(
        {row.id for row in source_products} & active_after
    )
    remaining_sku_count = int(
        session.scalar(
            select(func.count())
            .select_from(SkuRow)
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.origin_source_file_id == source_file_id,
                SkuRow.deleted_at.is_(None),
                SkuRow.status != "ARCHIVED",
            )
            .execution_options(include_deleted=True)
        )
        or 0
    )
    now = utcnow()
    job.file_rollback_at = now
    session.add(
        ProductAuditEventRow(
            tenant_id=tenant_id,
            product_id=None,
            entity_type="PRODUCT",
            entity_id=source_file_id,
            action="import.file_rolled_back",
            before={
                "filename": job.source_file.original_filename,
                "source_file_id": source_file_id,
                "sku_count": len(source_skus),
                "product_count": len(source_products),
            },
            after={
                "deleted_sku_count": deleted_sku_count,
                "archived_product_count": archived_product_count,
                "retained_product_count": retained_product_count,
            },
            actor_membership_id=membership_id,
            occurred_at=now,
        )
    )
    _update_batch_status_after_file_rollback(
        session,
        tenant_id=tenant_id,
        batch_id=job.batch_id,
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "IMPORT_FILE_ROLLBACK_CONFLICT",
            "撤回过程中商品库发生变化，请刷新后重试。",
            kind="conflict",
        ) from exc

    return CatalogImportFileRollbackResponse(
        source_file_id=source_file_id,
        import_job_id=job.id,
        status="REVOKED",
        deleted_sku_count=deleted_sku_count,
        archived_product_count=archived_product_count,
        retained_product_count=retained_product_count,
        remaining_sku_count=remaining_sku_count,
    )
