from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..db_models import ImportJobRow, SourceFileRow
from ..file_security_models import MediaObjectRow, WorkerJobRow


def add_file_security_records(
    session: Session,
    *,
    media: MediaObjectRow,
    source: SourceFileRow,
    import_job: ImportJobRow,
    worker_job: WorkerJobRow,
) -> None:
    session.add(media)
    session.flush()
    session.add(source)
    session.flush()
    session.add(import_job)
    session.flush()
    session.add(worker_job)


def claim_worker_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    now: datetime,
    worker_id: str,
    lease_expires_at: datetime,
) -> WorkerJobRow | None:
    row = session.scalar(
        select(WorkerJobRow)
        .where(
            WorkerJobRow.tenant_id == tenant_id,
            WorkerJobRow.id == job_id,
            or_(
                and_(
                    WorkerJobRow.status.in_(("PENDING", "RETRY")),
                    WorkerJobRow.available_at <= now,
                ),
                and_(
                    WorkerJobRow.status == "RUNNING",
                    WorkerJobRow.lease_expires_at.is_not(None),
                    WorkerJobRow.lease_expires_at <= now,
                ),
            ),
        )
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    row.status = "RUNNING"
    row.attempt_count += 1
    row.lease_owner = worker_id
    row.lease_expires_at = lease_expires_at
    row.safe_error_code = None
    row.safe_error_message = None
    return row


def next_due_job_id(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> UUID | None:
    return session.scalar(
        select(WorkerJobRow.id)
        .where(
            WorkerJobRow.tenant_id == tenant_id,
            or_(
                and_(
                    WorkerJobRow.status.in_(("PENDING", "RETRY")),
                    WorkerJobRow.available_at <= now,
                ),
                and_(
                    WorkerJobRow.status == "RUNNING",
                    WorkerJobRow.lease_expires_at.is_not(None),
                    WorkerJobRow.lease_expires_at <= now,
                ),
            ),
        )
        .order_by(WorkerJobRow.available_at, WorkerJobRow.created_at, WorkerJobRow.id)
        .limit(1)
    )


def load_file_job_graph(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
) -> tuple[WorkerJobRow, MediaObjectRow, SourceFileRow, ImportJobRow] | None:
    row = session.scalar(
        select(WorkerJobRow).where(
            WorkerJobRow.tenant_id == tenant_id,
            WorkerJobRow.id == job_id,
        )
    )
    if row is None:
        return None
    media = session.scalar(
        select(MediaObjectRow).where(
            MediaObjectRow.tenant_id == tenant_id,
            MediaObjectRow.id == row.media_object_id,
        )
    )
    source = session.scalar(
        select(SourceFileRow).where(
            SourceFileRow.tenant_id == tenant_id,
            SourceFileRow.id == row.source_file_id,
        )
    )
    import_job = session.scalar(
        select(ImportJobRow).where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.id == row.import_job_id,
        )
    )
    if media is None or source is None or import_job is None:
        return None
    return row, media, source, import_job
