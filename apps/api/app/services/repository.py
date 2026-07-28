from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db_models import ImportJobRow, ReviewItemRow, SupplierRow
from ..models import ImportJob, JobStatus, ReviewField, ReviewItem, Supplier


SEED_SUPPLIERS = (
    ("SUP-001", "青禾宠物用品", "饮水与喂食", 426, "good"),
    ("SUP-002", "远航户外宠物制品", "围栏与玩具", 182, "good"),
    ("SUP-003", "云宠智能设备", "智能硬件", 71, "warning"),
)


def seed_suppliers(session: Session) -> None:
    if session.scalar(select(func.count()).select_from(SupplierRow)):
        return
    session.add_all([
        SupplierRow(
            id=row[0],
            supplier_code=row[0],
            name=row[1],
            category=row[2],
            category_summary=row[2],
            active_skus=row[3],
            health=row[4],
        )
        for row in SEED_SUPPLIERS
    ])
    session.commit()


def supplier_models(session: Session, *, tenant_id: UUID) -> list[Supplier]:
    review_counts = dict(session.execute(
        select(ReviewItemRow.supplier_name, func.count(ReviewItemRow.id))
        .where(
            ReviewItemRow.tenant_id == tenant_id,
            ReviewItemRow.status == "pending",
        )
        .group_by(ReviewItemRow.supplier_name)
    ).all())
    rows = session.scalars(
        select(SupplierRow)
        .where(SupplierRow.tenant_id == tenant_id)
        .order_by(SupplierRow.id)
    ).all()
    return [Supplier(
        id=row.id,
        name=row.name,
        category=row.category,
        active_skus=row.active_skus,
        review_count=int(review_counts.get(row.name, 0)),
        freshness="今天" if row.updated_at.date() == datetime.now(row.updated_at.tzinfo).date() else row.updated_at.date().isoformat(),
        health=row.health,
    ) for row in rows]


def import_job_model(
    row: ImportJobRow,
    *,
    warning_limit: int | None = None,
    issue_limit: int | None = None,
) -> ImportJob:
    latest_worker = (
        max(row.worker_jobs, key=lambda worker: worker.created_at)
        if row.worker_jobs
        else None
    )
    result_details = dict(latest_worker.checkpoint) if latest_worker else {}
    raw_warnings = result_details.get("warnings", [])
    all_warning_messages = (
        [str(warning) for warning in raw_warnings]
        if isinstance(raw_warnings, list)
        else []
    )
    try:
        warning_total = max(
            len(all_warning_messages),
            int(result_details.get("warning_total", row.warnings_count)),
        )
    except (TypeError, ValueError):
        warning_total = max(len(all_warning_messages), row.warnings_count)
    warning_messages = (
        all_warning_messages[:warning_limit]
        if warning_limit is not None
        else all_warning_messages
    )
    if warning_total > len(warning_messages):
        result_details["warnings"] = warning_messages
        result_details["warnings_truncated"] = warning_total - len(warning_messages)
    raw_issues = result_details.get("issues", [])
    all_issues = (
        [dict(issue) for issue in raw_issues if isinstance(issue, dict)]
        if isinstance(raw_issues, list)
        else []
    )
    try:
        issue_total = max(
            len(all_issues),
            int(result_details.get("issue_total", len(all_issues))),
        )
    except (TypeError, ValueError):
        issue_total = len(all_issues)
    visible_issues = (
        all_issues[:issue_limit]
        if issue_limit is not None
        else all_issues
    )
    result_details["issues"] = visible_issues
    result_details["issue_total"] = issue_total
    if issue_total > len(visible_issues):
        result_details["issues_truncated"] = issue_total - len(visible_issues)
    else:
        result_details["issues_truncated"] = 0
    try:
        observable_progress = max(
            row.progress,
            int(result_details.get("import_progress", row.progress)),
        )
    except (TypeError, ValueError):
        observable_progress = row.progress
    return ImportJob(
        id=row.id,
        filename=row.source_file.original_filename,
        supplier=row.supplier_name,
        source_type=row.source_type,
        detected_type=row.source_file.detected_type,
        status=JobStatus(row.status),
        progress=max(0, min(100, observable_progress)),
        products=row.products_count,
        warnings=row.warnings_count,
        created_at=row.created_at.astimezone().strftime("%H:%M"),
        parser=row.source_file.parser,
        extension_matches=row.source_file.extension_matches,
        error_message=row.error_message,
        warning_messages=warning_messages,
        result_details=result_details,
    )


def get_import_job(
    session: Session,
    job_id: str,
    *,
    tenant_id: UUID,
) -> ImportJobRow | None:
    return session.scalar(
        select(ImportJobRow)
        .options(
            selectinload(ImportJobRow.source_file),
            selectinload(ImportJobRow.worker_jobs),
        )
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.id == job_id,
        )
    )


def list_import_job_models(
    session: Session,
    *,
    tenant_id: UUID,
    limit: int = 100,
) -> list[ImportJob]:
    rows = session.scalars(
        select(ImportJobRow)
        .options(
            selectinload(ImportJobRow.source_file),
            selectinload(ImportJobRow.worker_jobs),
        )
        .where(ImportJobRow.tenant_id == tenant_id)
        .order_by(ImportJobRow.created_at.desc())
        .limit(limit)
    ).all()
    # Polling/list responses stay bounded. The per-job endpoint still exposes
    # every persisted warning on demand.
    return [
        import_job_model(row, warning_limit=20, issue_limit=20)
        for row in rows
    ]


def review_item_model(row: ReviewItemRow) -> ReviewItem:
    return ReviewItem(
        id=row.id,
        job_id=row.job_id,
        status=row.status,
        name=row.name,
        model=row.model,
        category=row.category,
        supplier=row.supplier_name,
        source=row.source_filename,
        location=row.source_location,
        image_status=row.image_status,
        fields=[ReviewField.model_validate(field) for field in row.fields],
    )


def list_review_item_models(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[ReviewItem]:
    statement = (
        select(ReviewItemRow)
        .where(ReviewItemRow.tenant_id == tenant_id)
        .order_by(ReviewItemRow.created_at.desc())
        .limit(limit)
    )
    if job_id:
        statement = statement.where(ReviewItemRow.job_id == job_id)
    if status:
        statement = statement.where(ReviewItemRow.status == status)
    return [review_item_model(row) for row in session.scalars(statement).all()]
