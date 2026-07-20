from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from ..data import PRODUCTS
from ..domain.errors import ApplicationError
from ..models import (
    FileDetectionResponse,
    ImportJob,
    PriceCalculationRequest,
    PriceCalculationResponse,
    Product,
    ReviewApprovalResponse,
    ReviewItem,
    ReviewItemUpdate,
    Supplier,
    SupplierFileImportResponse,
)
from ..repositories.legacy_repository import (
    find_supplier,
    get_review_item,
)
from ..repositories.file_security_repository import add_file_security_records
from ..adapters.object_storage import get_object_storage
from ..file_security_models import MediaObjectRow, WorkerJobRow
from ..db_models import ImportJobRow, SourceFileRow
from ..model_mixins import utcnow
from ..services.file_detection import detect_file_path, detect_file_type
from ..services.import_processing import new_id
from ..services.pricing import calculate_price
from ..services.repository import (
    get_import_job,
    import_job_model,
    list_import_job_models,
    list_review_item_models,
    review_item_model,
    supplier_models,
)
from ..services.storage import UploadTooLargeError, store_upload
from ..workers.file_processing import inline_worker_enabled, process_file_worker_job


def _require_permission(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def list_suppliers(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> list[Supplier]:
    _require_permission(permissions, "supplier.view")
    return supplier_models(session, tenant_id=tenant_id)


def list_imports(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    limit: int,
) -> list[ImportJob]:
    _require_permission(permissions, "product.import")
    return list_import_job_models(session, tenant_id=tenant_id, limit=limit)


def get_import(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: str,
) -> ImportJob:
    _require_permission(permissions, "product.import")
    row = get_import_job(session, job_id, tenant_id=tenant_id)
    if row is None:
        raise ApplicationError("IMPORT_NOT_FOUND", "Import job was not found.", kind="not_found")
    return import_job_model(row)


def detect_upload(filename: str, header: bytes) -> FileDetectionResponse:
    return detect_file_type(filename, header)


async def create_import(
    session: Session,
    *,
    upload: Any,
    supplier_id: str | None,
    source_type: str,
    tenant_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
) -> SupplierFileImportResponse:
    _require_permission(permissions, "product.import")
    original_filename = Path(upload.filename or "unnamed").name
    normalized_source_type = source_type.strip().upper()[:40] or "UNKNOWN"
    supplier = (
        find_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
        if supplier_id
        else None
    )
    if supplier_id and supplier is None:
        raise ApplicationError("SUPPLIER_NOT_FOUND", "Supplier was not found.", kind="not_found")
    if normalized_source_type in {"SUPPLIER_CATALOG", "SUPPLIER_QUOTE"} and supplier is None:
        raise ApplicationError(
            "SUPPLIER_REQUIRED",
            "Select a supplier before importing a supplier catalog or quote.",
        )
    source_id = new_id("SRC")
    job_id = new_id("JOB")
    storage = get_object_storage()
    try:
        stored = await store_upload(
            upload,
            source_id,
            tenant_id=tenant_id,
            storage=storage,
        )
    except UploadTooLargeError as exc:
        raise ApplicationError("UPLOAD_TOO_LARGE", str(exc), kind="too_large") from exc

    with storage.materialize(stored.object_key) as quarantine_path:
        detection = detect_file_path(quarantine_path, original_filename)
    now = utcnow()
    media_id = uuid4()
    worker_job_id = uuid4()
    media = MediaObjectRow(
        id=media_id,
        tenant_id=tenant_id,
        object_key=stored.object_key,
        zone="QUARANTINE",
        original_filename=original_filename,
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        declared_media_type=stored.declared_media_type,
        detected_media_type=detection.detected_type,
        status="QUARANTINED",
        scan_status="PENDING",
        scan_result={},
        created_by_user_id=user_id,
    )
    local_quarantine_path = storage.local_path(stored.object_key)
    source = SourceFileRow(
        id=source_id,
        tenant_id=tenant_id,
        media_object_id=media_id,
        security_status="PENDING_SCAN",
        original_filename=original_filename,
        stored_filename=stored.stored_filename,
        local_path=str(local_quarantine_path) if local_quarantine_path else "",
        sha256=stored.sha256,
        byte_size=stored.byte_size,
        extension=detection.extension,
        detected_type=detection.detected_type,
        extension_matches=detection.extension_matches,
        parser=detection.parser,
        warning=detection.warning,
    )
    import_job = ImportJobRow(
        id=job_id,
        tenant_id=tenant_id,
        source_file_id=source_id,
        supplier_id=supplier.id if supplier else None,
        supplier_name=supplier.name if supplier else "Supplier pending selection",
        source_type=normalized_source_type,
        status="scanning",
        progress=5,
        warnings_count=1 if detection.warning else 0,
    )
    worker_job = WorkerJobRow(
        id=worker_job_id,
        tenant_id=tenant_id,
        job_type="FILE_SCAN_AND_PARSE",
        media_object_id=media_id,
        source_file_id=source_id,
        import_job_id=job_id,
        status="PENDING",
        attempt_count=0,
        max_attempts=int(os.getenv("FILE_WORKER_MAX_ATTEMPTS", "3")),
        available_at=now,
        checkpoint={},
        idempotency_key=f"file-scan-parse:{source_id}:{stored.sha256}",
    )
    add_file_security_records(
        session,
        media=media,
        source=source,
        import_job=import_job,
        worker_job=worker_job,
    )
    session.commit()

    worker_result = None
    dialect = session.bind.dialect.name if session.bind is not None else "unknown"
    if inline_worker_enabled(database_dialect=dialect):
        worker_result = process_file_worker_job(
            session,
            tenant_id=tenant_id,
            job_id=worker_job_id,
            worker_id="inline-api-worker",
            storage=storage,
        )
    session.expire_all()
    completed = get_import_job(session, job_id, tenant_id=tenant_id)
    if completed is None:
        raise ApplicationError(
            "IMPORT_CREATION_FAILED",
            "Import job could not be loaded after processing.",
            kind="internal",
        )
    return SupplierFileImportResponse(
        **import_job_model(completed).model_dump(),
        ai_task_id=str(worker_result.ai_task_id) if worker_result and worker_result.ai_task_id else None,
        candidate_fields=worker_result.candidate_fields if worker_result else 0,
        candidate_status=worker_result.candidate_status if worker_result else None,
        candidate_idempotent=worker_result.candidate_idempotent if worker_result else False,
    )


def list_review_items(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    job_id: str | None,
    review_status: str | None,
    limit: int,
) -> list[ReviewItem]:
    _require_permission(permissions, "product.review")
    return list_review_item_models(
        session,
        tenant_id=tenant_id,
        job_id=job_id,
        status=review_status,
        limit=limit,
    )


def update_review_item(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    item_id: str,
    request: ReviewItemUpdate,
) -> ReviewItem:
    _require_permission(permissions, "product.review")
    row = get_review_item(session, tenant_id=tenant_id, item_id=item_id)
    if row is None:
        raise ApplicationError("REVIEW_ITEM_NOT_FOUND", "Review item was not found.", kind="not_found")
    fields = [dict(field) for field in row.fields]
    valid_keys = {field.get("key") for field in fields}
    unknown_keys = set(request.normalized_values) - valid_keys
    if unknown_keys:
        raise ApplicationError(
            "UNKNOWN_REVIEW_FIELD",
            f"Unknown fields: {', '.join(sorted(unknown_keys))}",
        )
    for field in fields:
        key = field.get("key")
        if key in request.normalized_values:
            field["normalized"] = request.normalized_values[key].strip()
    row.fields = fields
    row.status = "pending"
    session.commit()
    session.refresh(row)
    return review_item_model(row)


def approve_review_item(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    item_id: str,
) -> ReviewApprovalResponse:
    _require_permission(permissions, "product.review")
    row = get_review_item(session, tenant_id=tenant_id, item_id=item_id)
    if row is None:
        raise ApplicationError("REVIEW_ITEM_NOT_FOUND", "Review item was not found.", kind="not_found")
    row.status = "approved"
    session.commit()
    return ReviewApprovalResponse(id=row.id, status=row.status, image_status=row.image_status)


def list_products(
    *,
    query: str,
    supplier: str | None,
    approved_images_only: bool,
) -> list[Product]:
    normalized_query = query.casefold().strip()
    rows = PRODUCTS
    if normalized_query:
        rows = [
            row
            for row in rows
            if normalized_query
            in " ".join(
                [row.name, row.model, row.category, row.supplier, *row.tags]
            ).casefold()
        ]
    if supplier:
        rows = [row for row in rows if row.supplier == supplier]
    if approved_images_only:
        rows = [row for row in rows if row.image_status == "APPROVED"]
    return rows


def calculate_pricing(request: PriceCalculationRequest) -> PriceCalculationResponse:
    return calculate_price(request)
