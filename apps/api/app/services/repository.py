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


def import_job_model(row: ImportJobRow) -> ImportJob:
    return ImportJob(
        id=row.id,
        filename=row.source_file.original_filename,
        supplier=row.supplier_name,
        detected_type=row.source_file.detected_type,
        status=JobStatus(row.status),
        progress=row.progress,
        products=row.products_count,
        warnings=row.warnings_count,
        created_at=row.created_at.astimezone().strftime("%H:%M"),
        parser=row.source_file.parser,
        extension_matches=row.source_file.extension_matches,
        error_message=row.error_message,
    )


def get_import_job(
    session: Session,
    job_id: str,
    *,
    tenant_id: UUID,
) -> ImportJobRow | None:
    return session.scalar(
        select(ImportJobRow)
        .options(selectinload(ImportJobRow.source_file))
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
        .options(selectinload(ImportJobRow.source_file))
        .where(ImportJobRow.tenant_id == tenant_id)
        .order_by(ImportJobRow.created_at.desc())
        .limit(limit)
    ).all()
    return [import_job_model(row) for row in rows]


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
