from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.object_storage import get_object_storage
from ..model_mixins import mark_deleted, utcnow
from ..product_supplier_models import ProductImageRow


logger = logging.getLogger(__name__)

# These are the providers written by the product image upload/import paths.
# ``LOCAL_DEMO`` is deliberately excluded: demo placeholders are not objects
# owned by the product tenant and should never be removed from storage.
_MANAGED_STORAGE_PROVIDERS = frozenset(
    {
        "S3",
        "R2",
        "LOCAL",
        "LOCAL-S3-COMPATIBLE",
        "LOCAL_S3_COMPATIBLE",
    }
)


@dataclass(frozen=True)
class ProductImageCleanupResult:
    """Summary of the best-effort object-storage cleanup."""

    removed_image_count: int = 0
    deleted_storage_image_count: int = 0
    preserved_external_image_count: int = 0
    retained_shared_image_count: int = 0
    storage_delete_failures: int = 0


def _is_external_image(image: ProductImageRow) -> bool:
    provider = str(image.storage_provider or "").strip().upper()
    object_key = str(image.object_key or "").strip().lower()
    return provider in {"EXTERNAL", "REMOTE", "URL"} or object_key.startswith(
        ("http://", "https://")
    )


def _is_managed_image(image: ProductImageRow, *, tenant_id: UUID) -> bool:
    provider = str(image.storage_provider or "").strip().upper()
    object_key = str(image.object_key or "").strip()
    if provider not in _MANAGED_STORAGE_PROVIDERS:
        return False
    # Product-owned objects are always tenant-scoped. Refuse to delete an
    # unrecognised key even when a legacy row claims to be storage-managed.
    return bool(object_key) and object_key.startswith(f"tenants/{tenant_id}/")


def cleanup_product_images(
    session: Session,
    *,
    tenant_id: UUID,
    product_ids: list[UUID] | tuple[UUID, ...] | set[UUID],
    at: datetime | None = None,
) -> ProductImageCleanupResult:
    """Remove objects for products that are no longer active.

    Product and SKU records are intentionally soft-deleted for audit/history.
    Image rows follow the same lifecycle, but managed files are removed from
    object storage at this point. The operation is best-effort: an R2 outage
    must not make a successful product deletion fail. Failed rows remain
    available for a later cleanup retry.

    External URLs and demo placeholders are never sent to object storage.
    Objects still referenced by another active image row are retained as an
    additional guard against deleting shared/legacy files.
    """

    ids = list(dict.fromkeys(product_ids))
    if not ids:
        return ProductImageCleanupResult()

    images = session.scalars(
        select(ProductImageRow)
        .where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.product_id.in_(ids),
        )
        .execution_options(include_deleted=True)
    ).all()
    if not images:
        return ProductImageCleanupResult()

    candidate_keys = {
        str(image.object_key).strip()
        for image in images
        if _is_managed_image(image, tenant_id=tenant_id)
        and str(image.object_key or "").strip()
    }
    shared_keys: set[str] = set()
    if candidate_keys:
        shared_keys = set(
            session.scalars(
                select(ProductImageRow.object_key).where(
                    ProductImageRow.tenant_id == tenant_id,
                    ProductImageRow.object_key.in_(candidate_keys),
                    ProductImageRow.deleted_at.is_(None),
                    ~ProductImageRow.product_id.in_(ids),
                )
            ).all()
        )

    storage = None
    storage_initialization_failed = False
    if candidate_keys - shared_keys:
        try:
            storage = get_object_storage()
        except Exception:
            # Keep deletion of the catalog independent from a temporarily
            # unavailable/misconfigured storage backend.
            storage_initialization_failed = True
            logger.exception(
                "product image cleanup could not initialise object storage",
                extra={"tenant_id": str(tenant_id), "product_ids": [str(i) for i in ids]},
            )

    now = at or utcnow()
    removed_image_count = 0
    deleted_storage_image_count = 0
    preserved_external_image_count = 0
    storage_delete_failures = 0

    for image in images:
        if _is_external_image(image):
            preserved_external_image_count += 1
            if image.deleted_at is None:
                mark_deleted(image, at=now)
                removed_image_count += 1
            continue

        if not _is_managed_image(image, tenant_id=tenant_id):
            continue
        object_key = str(image.object_key).strip()
        if object_key in shared_keys:
            continue
        if storage_initialization_failed or storage is None:
            storage_delete_failures += 1
            continue

        try:
            # Both the local adapter and S3 DeleteObject are idempotent, so a
            # retry also cleans rows whose object was already removed.
            storage.delete(object_key)
        except Exception:
            storage_delete_failures += 1
            logger.exception(
                "product image object deletion failed",
                extra={
                    "tenant_id": str(tenant_id),
                    "product_id": str(image.product_id),
                    "image_id": str(image.id),
                    "object_key": object_key,
                },
            )
            continue

        deleted_storage_image_count += 1
        if image.deleted_at is None:
            mark_deleted(image, at=now)
            removed_image_count += 1

    return ProductImageCleanupResult(
        removed_image_count=removed_image_count,
        deleted_storage_image_count=deleted_storage_image_count,
        preserved_external_image_count=preserved_external_image_count,
        retained_shared_image_count=len(shared_keys),
        storage_delete_failures=storage_delete_failures,
    )
