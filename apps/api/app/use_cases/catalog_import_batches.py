from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..catalog_operation_models import CatalogImportBatchRow
from ..db_models import ImportJobRow
from ..domain.errors import ApplicationError
from ..identity_models import TenantRow
from ..model_mixins import utcnow
from ..models import (
    CatalogImportBatch,
    CatalogImportBatchCategory,
    CatalogImportBatchRollbackResponse,
)
from ..product_center_models import SkuRow
from ..product_supplier_models import (
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
)
from ..services.repository import import_job_model
from ..services.product_image_cleanup import cleanup_product_images
from .product_center import batch_delete_skus


UNCLASSIFIED_CATEGORY_ID = "__unclassified__"


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


def create_import_batch(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    expected_file_count: int,
) -> CatalogImportBatchRow:
    _require_catalog_import_access(permissions)
    batch = CatalogImportBatchRow(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        created_by_membership_id=membership_id,
        expected_file_count=expected_file_count,
        status="ACTIVE",
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def _load_batches(
    session: Session,
    *,
    tenant_id: UUID,
    limit: int,
) -> tuple[list[CatalogImportBatchRow], dict[UUID, list[ImportJobRow]]]:
    batches = session.scalars(
        select(CatalogImportBatchRow)
        .where(
            CatalogImportBatchRow.tenant_id == tenant_id,
            CatalogImportBatchRow.deleted_at.is_(None),
        )
        .order_by(CatalogImportBatchRow.created_at.desc())
        .limit(limit)
    ).all()
    if not batches:
        return [], {}
    batch_ids = [row.id for row in batches]
    jobs = session.scalars(
        select(ImportJobRow)
        .options(
            selectinload(ImportJobRow.source_file),
            selectinload(ImportJobRow.worker_jobs),
        )
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.batch_id.in_(batch_ids),
        )
        .order_by(ImportJobRow.created_at.asc())
    ).all()
    by_batch: dict[UUID, list[ImportJobRow]] = defaultdict(list)
    for job in jobs:
        if job.batch_id is not None:
            by_batch[job.batch_id].append(job)
    return batches, by_batch


def list_import_batches(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[CatalogImportBatch]:
    _require_catalog_import_access(permissions)
    batches, jobs_by_batch = _load_batches(
        session,
        tenant_id=tenant_id,
        limit=limit,
    )
    if not batches:
        return []

    batch_ids = [row.id for row in batches]
    category_counts = session.execute(
        select(
            SkuRow.rollback_owner_batch_id,
            ProductRow.category_id,
            func.count(SkuRow.id),
        )
        .select_from(SkuRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.rollback_owner_batch_id.in_(batch_ids),
            SkuRow.deleted_at.is_(None),
            SkuRow.status != "ARCHIVED",
        )
        .group_by(
            SkuRow.rollback_owner_batch_id,
            ProductRow.category_id,
        )
    ).all()
    category_rows = session.scalars(
        select(ProductCategoryRow)
        .where(ProductCategoryRow.tenant_id == tenant_id)
        .execution_options(include_deleted=True)
    ).all()
    category_map = {row.id: row for row in category_rows}
    category_totals_by_batch: dict[UUID, dict[UUID | None, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    remaining_by_batch: dict[UUID, int] = defaultdict(int)
    for batch_id, category_id, sku_count in category_counts:
        if batch_id is None:
            continue
        count = int(sku_count)
        remaining_by_batch[batch_id] += count
        category_totals_by_batch[batch_id][category_id] += count
        category = category_map.get(category_id) if category_id is not None else None
        if category is not None and category.parent_id is not None:
            category_totals_by_batch[batch_id][category.parent_id] += count

    categories_by_batch: dict[UUID, list[CatalogImportBatchCategory]] = defaultdict(list)
    for batch_id, totals in category_totals_by_batch.items():
        for category_id, sku_count in totals.items():
            category = category_map.get(category_id) if category_id is not None else None
            parent = (
                category_map.get(category.parent_id)
                if category is not None and category.parent_id is not None
                else None
            )
            categories_by_batch[batch_id].append(
                CatalogImportBatchCategory(
                    id=str(category_id) if category_id is not None else UNCLASSIFIED_CATEGORY_ID,
                    name=(
                        f"{parent.name} / {category.name}"
                        if parent is not None and category is not None
                        else category.name if category is not None else "未分类"
                    ),
                    sku_count=sku_count,
                )
            )

    result: list[CatalogImportBatch] = []
    for batch in batches:
        jobs = jobs_by_batch.get(batch.id, [])
        result.append(
            CatalogImportBatch(
                id=batch.id,
                status=batch.status,
                expected_file_count=batch.expected_file_count,
                file_count=len(jobs),
                remaining_sku_count=remaining_by_batch.get(batch.id, 0),
                created_at=batch.created_at.isoformat(),
                jobs=[import_job_model(job, warning_limit=20, issue_limit=20) for job in jobs],
                categories=sorted(
                    categories_by_batch.get(batch.id, []),
                    key=lambda category: (
                        category_map.get(UUID(category.id)).sort_order
                        if category.id != UNCLASSIFIED_CATEGORY_ID
                        and category_map.get(UUID(category.id)) is not None
                        else 1_000_000,
                        category.name.casefold(),
                    ),
                ),
            )
        )
    return result


def _category_ids_for_rollback(
    session: Session,
    *,
    tenant_id: UUID,
    category_id: str | None,
) -> set[UUID] | None:
    if category_id is None:
        return None
    if category_id == UNCLASSIFIED_CATEGORY_ID:
        return set()
    try:
        parsed_id = UUID(category_id)
    except ValueError as exc:
        raise ApplicationError(
            "IMPORT_BATCH_CATEGORY_INVALID",
            "所选分类不存在，请刷新后重试。",
            kind="validation_failed",
        ) from exc
    category = session.scalar(
        select(ProductCategoryRow).where(
            ProductCategoryRow.tenant_id == tenant_id,
            ProductCategoryRow.id == parsed_id,
            ProductCategoryRow.deleted_at.is_(None),
        )
    )
    if category is None:
        raise ApplicationError(
            "IMPORT_BATCH_CATEGORY_NOT_FOUND",
            "所选分类不存在，请刷新后重试。",
            kind="not_found",
        )
    children = session.scalars(
        select(ProductCategoryRow.id).where(
            ProductCategoryRow.tenant_id == tenant_id,
            ProductCategoryRow.parent_id == parsed_id,
            ProductCategoryRow.deleted_at.is_(None),
        )
    ).all()
    return {parsed_id, *children}


def rollback_import_batch(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    membership_id: UUID,
    permissions: frozenset[str],
    batch_id: UUID,
    category_id: str | None,
) -> CatalogImportBatchRollbackResponse:
    _require_catalog_import_access(permissions)
    # All operations that can grant or consume rollback ownership serialize on
    # the tenant row. The batch lock comes second everywhere, avoiding upload,
    # worker and duplicate-rollback races in PostgreSQL.
    tenant_exists = session.scalar(
        select(TenantRow.id)
        .where(TenantRow.id == tenant_id)
        .with_for_update()
    )
    batch = session.scalar(
        select(CatalogImportBatchRow)
        .where(
            CatalogImportBatchRow.tenant_id == tenant_id,
            CatalogImportBatchRow.id == batch_id,
            CatalogImportBatchRow.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if tenant_exists is None or batch is None:
        raise ApplicationError(
            "IMPORT_BATCH_NOT_FOUND",
            "导入批次不存在。",
            kind="not_found",
        )
    if batch.status == "REVOKED":
        return CatalogImportBatchRollbackResponse(
            batch_id=batch.id,
            status=batch.status,
            deleted_sku_count=0,
            archived_product_count=0,
            removed_image_count=0,
            deleted_storage_image_count=0,
            preserved_external_image_count=0,
            retained_shared_image_count=0,
            storage_delete_failures=0,
            remaining_sku_count=0,
        )
    jobs = session.scalars(
        select(ImportJobRow).where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.batch_id == batch_id,
        )
    ).all()
    if any(job.status in {"scanning", "parsing"} for job in jobs):
        raise ApplicationError(
            "IMPORT_BATCH_STILL_RUNNING",
            "该批次仍在导入，请完成后再撤回。",
            kind="conflict",
        )
    if not jobs:
        raise ApplicationError(
            "IMPORT_BATCH_EMPTY",
            "该批次没有可撤回的导入文件。",
            kind="validation_failed",
        )

    category_ids = _category_ids_for_rollback(
        session,
        tenant_id=tenant_id,
        category_id=category_id,
    )
    sku_query = (
        select(SkuRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == SkuRow.tenant_id)
            & (ProductRow.id == SkuRow.product_id),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.rollback_owner_batch_id == batch_id,
            SkuRow.deleted_at.is_(None),
            SkuRow.status != "ARCHIVED",
        )
        .execution_options(include_deleted=True)
        .with_for_update()
    )
    if category_ids == set():
        sku_query = sku_query.where(ProductRow.category_id.is_(None))
    elif category_ids is not None:
        sku_query = sku_query.where(ProductRow.category_id.in_(category_ids))
    scoped_skus = session.scalars(sku_query).all()
    product_ids = list(dict.fromkeys(row.product_id for row in scoped_skus))
    active_sku_ids = [row.id for row in scoped_skus]
    if category_id is not None and not product_ids:
        raise ApplicationError(
            "IMPORT_BATCH_CATEGORY_EMPTY",
            "该批次在所选分类下没有可撤回商品。",
            kind="validation_failed",
        )

    deleted_sku_count = 0
    if active_sku_ids:
        result = batch_delete_skus(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            membership_id=membership_id,
            permissions=permissions,
            sku_ids=active_sku_ids,
            commit=False,
            # The rollback response reports image cleanup details below, so
            # perform the cleanup once after the final product scope is known.
            cleanup_images=False,
        )
        deleted_sku_count = int(result["success_count"])

    remaining_by_product: dict[UUID, int] = {}
    if product_ids:
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
    archived_product_ids = [
        product_id
        for product_id in product_ids
        if remaining_by_product.get(product_id, 0) == 0
    ]
    retained_product_ids = set(product_ids) - set(archived_product_ids)

    all_images = (
        session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.product_id.in_(product_ids),
            )
            .execution_options(include_deleted=True)
        ).all()
        if product_ids
        else []
    )
    retained_shared_image_count = sum(
        1
        for image in all_images
        if image.product_id in retained_product_ids and image.deleted_at is None
    )
    now = utcnow()
    cleanup = cleanup_product_images(
        session,
        tenant_id=tenant_id,
        product_ids=archived_product_ids,
        at=now,
    )
    removed_image_count = cleanup.removed_image_count
    deleted_storage_image_count = cleanup.deleted_storage_image_count
    preserved_external_image_count = cleanup.preserved_external_image_count
    storage_delete_failures = cleanup.storage_delete_failures
    remaining_sku_count = int(
        session.scalar(
            select(func.count())
            .select_from(SkuRow)
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.rollback_owner_batch_id == batch_id,
                SkuRow.deleted_at.is_(None),
                SkuRow.status != "ARCHIVED",
            )
        )
        or 0
    )
    if remaining_sku_count == 0:
        batch.status = "REVOKED"
        batch.revoked_at = now
    elif deleted_sku_count > 0 or batch.status == "PARTIALLY_REVOKED":
        batch.status = "PARTIALLY_REVOKED"
        batch.revoked_at = None
    batch.updated_at = now
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "IMPORT_BATCH_ROLLBACK_CONFLICT",
            "撤回过程中商品库发生变化，请刷新后重试。",
            kind="conflict",
        ) from exc

    return CatalogImportBatchRollbackResponse(
        batch_id=batch.id,
        status=batch.status,
        deleted_sku_count=deleted_sku_count,
        archived_product_count=len(archived_product_ids),
        # Images intentionally remain untouched. The current schema has no
        # batch-level image provenance, so deleting by product would risk
        # removing manual or earlier-import assets.
        removed_image_count=0,
        deleted_storage_image_count=0,
        preserved_external_image_count=0,
        retained_shared_image_count=0,
        storage_delete_failures=0,
        remaining_sku_count=remaining_sku_count,
    )
