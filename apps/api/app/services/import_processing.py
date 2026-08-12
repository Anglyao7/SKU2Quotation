from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from uuid import UUID

from sqlalchemy import delete, select

from ..database import SessionLocal, set_request_context
from ..db_models import ImportJobRow, ReviewItemRow
from .file_detection import detect_file_path
from .parsers import parse_document


def new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%y%m%d')}-{uuid4().hex[:8].upper()}"


def process_import(
    job_id: str,
    *,
    tenant_id: UUID | None = None,
    source_path: Path | None = None,
) -> None:
    with SessionLocal() as session:
        if tenant_id is not None:
            set_request_context(
                session,
                organization_id=UUID(int=0),
                tenant_id=tenant_id,
                user_id=UUID(int=0),
            )
        statement = select(ImportJobRow).where(ImportJobRow.id == job_id)
        if tenant_id is not None:
            statement = statement.where(ImportJobRow.tenant_id == tenant_id)
        job = session.scalar(statement)
        if job is None:
            return
        source_file = job.source_file
        if source_file.security_status not in {"ACCEPTED", "LEGACY_ACCEPTED"}:
            job.status = "failed"
            job.error_message = "文件尚未完成接收，暂时无法解析。"
            session.commit()
            return
        path = source_path or Path(source_file.local_path)
        job.status = "parsing"
        job.progress = 25
        session.commit()

        try:
            detection = detect_file_path(path, source_file.original_filename)
            result = parse_document(path, detection)
            session.execute(delete(ReviewItemRow).where(ReviewItemRow.job_id == job.id))

            for record in result.records:
                session.add(ReviewItemRow(
                    id=new_id("REV"),
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    status="pending",
                    name=record.name,
                    model=record.model,
                    category=record.category,
                    supplier_name=job.supplier_name,
                    source_filename=source_file.original_filename,
                    source_location=record.location,
                    image_status="SOURCE",
                    fields=record.fields,
                    raw_payload=record.raw_payload,
                ))

            warning_count = len(result.warnings) + (0 if source_file.extension_matches else 1)
            job.products_count = len(result.records)
            job.warnings_count = warning_count
            job.progress = 100
            job.status = "needs_review"
            job.error_message = "；".join(result.warnings[:3]) or None
            if result.supported and not result.records:
                job.error_message = job.error_message or "没有识别到可审核的产品记录"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:
            session.rollback()
            job = session.scalar(statement)
            if job:
                job.status = "failed"
                job.progress = 100
                job.warnings_count = max(job.warnings_count, 1)
                job.error_message = f"解析失败：{type(exc).__name__}。原文件已保留，可重试或人工处理。"
                job.completed_at = datetime.now(timezone.utc)
                session.commit()
