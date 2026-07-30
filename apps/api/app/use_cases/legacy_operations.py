from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, set_request_context
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
from ..services.product_template_import import (
    PRODUCT_TEMPLATE_HEADERS,
    PRODUCT_TEMPLATE_SHEET,
)
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
    defer_inline_worker: bool = False,
) -> SupplierFileImportResponse:
    _require_permission(permissions, "product.import")
    original_filename = Path(upload.filename or "unnamed").name
    normalized_source_type = source_type.strip().upper()[:40] or "UNKNOWN"
    if normalized_source_type == "PRODUCT_TEMPLATE":
        # A fixed-template import writes authoritative products and may publish
        # public offers. Requiring all three capabilities prevents a scoped
        # importer from escalating into product editing or catalog publishing.
        _require_permission(permissions, "product.edit")
        _require_permission(permissions, "catalog.publish")
    if (
        normalized_source_type == "PRODUCT_TEMPLATE"
        and Path(original_filename).suffix.lower() != ".xlsx"
    ):
        raise ApplicationError(
            "PRODUCT_TEMPLATE_FORMAT_INVALID",
            "商品库只接受固定格式的 .xlsx 商品模版。",
        )
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
    if normalized_source_type == "PRODUCT_TEMPLATE" and (
        detection.detected_type != "OOXML / XLSX" or not detection.extension_matches
    ):
        try:
            storage.delete(stored.object_key)
        except Exception:
            pass
        raise ApplicationError(
            "PRODUCT_TEMPLATE_FORMAT_INVALID",
            "文件不是有效的 XLSX 商品模版，请使用根目录约定的商品模版格式。",
        )
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
        supplier_name=(
            supplier.name
            if supplier
            else "商品模版"
            if normalized_source_type == "PRODUCT_TEMPLATE"
            else "Supplier pending selection"
        ),
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
    if inline_worker_enabled(database_dialect=dialect) and not defer_inline_worker:
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


def inline_import_worker_enabled(session: Session) -> bool:
    dialect = session.bind.dialect.name if session.bind is not None else "unknown"
    return inline_worker_enabled(database_dialect=dialect)


def process_deferred_import(*, tenant_id: UUID, import_job_id: str) -> None:
    """Run an inline-profile job after the HTTP response has been sent."""

    with SessionLocal() as session:
        set_request_context(
            session,
            organization_id=UUID(int=0),
            tenant_id=tenant_id,
            user_id=UUID(int=0),
        )
        worker_job_id = session.scalar(
            select(WorkerJobRow.id)
            .where(
                WorkerJobRow.tenant_id == tenant_id,
                WorkerJobRow.import_job_id == import_job_id,
                WorkerJobRow.status.in_(("PENDING", "RETRY")),
            )
            .order_by(WorkerJobRow.created_at.desc())
            .limit(1)
        )
        session.rollback()
        if worker_job_id is None:
            return
        process_file_worker_job(
            session,
            tenant_id=tenant_id,
            job_id=worker_job_id,
            worker_id="deferred-api-worker",
            storage=get_object_storage(),
        )


def build_product_template_workbook() -> bytes:
    """Build the canonical, blank product-import workbook.

    The importer remains the source of truth for the worksheet and header
    contract; this download mirrors those constants exactly.
    """

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = PRODUCT_TEMPLATE_SHEET
    sheet.append(list(PRODUCT_TEMPLATE_HEADERS))

    header_fill = PatternFill(fill_type="solid", fgColor="23453B")
    header_font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
    header_border = Border(bottom=Side(style="medium", color="D18B67"))
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    instructions = {
        "商品名称": "必填。面向客户展示的商品名称。",
        "商品分类": "选填。填写“一级分类”或“一级分类/二级分类”，最多两级；留空自动归入“未分类”，且不会进入智能索引。",
        "商品型号": "选填。留空时系统根据商品名称、分类和供应商生成临时型号；填写时作为 SKU 唯一标识，重复型号只保留首次出现的行。",
        "供应商": "选填。用于关联进销存；同名供应商自动复用，不存在时自动创建。",
        "商品价格": "选填。留空时按 0.00 处理，商品仍会正常发布到前台。",
        "商品描述": "选填。商品详情说明。",
        "备注": "选填，仅作为商品补充说明。",
        "标签": "选填。多个标签使用中文或英文逗号分隔，最多 20 个。",
    }
    image_instruction = (
        "选填。可把真实图片直接插入对应单元格位置，"
        "也可填写可公开访问的 HTTP(S) 商品图片地址。"
    )
    widths = (28, 18, 22, 28, 14, 44, 24, 24, *([38] * 10))

    for index, (header, width) in enumerate(
        zip(PRODUCT_TEMPLATE_HEADERS, widths, strict=True),
        start=1,
    ):
        cell = sheet.cell(row=1, column=index)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = header_border
        cell.alignment = header_alignment
        cell.comment = Comment(
            instructions.get(header, image_instruction),
            "智贸云",
        )
        sheet.column_dimensions[get_column_letter(index)].width = width

    sheet.row_dimensions[1].height = 34
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(PRODUCT_TEMPLATE_HEADERS))}1"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = "1:1"

    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


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
