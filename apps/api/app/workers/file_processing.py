from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.orm import Session

from ..adapters.file_scanner import get_file_scanner
from ..adapters.object_storage import get_object_storage
from ..database import set_request_context
from ..ports.file_scanner import FileScannerPort
from ..ports.object_storage import ObjectStoragePort
from ..repositories.file_security_repository import claim_worker_job, load_file_job_graph
from ..services.import_processing import process_import
from ..services.product_intelligence.native_parser import NativeSupplierFileParserAdapter
from ..services.product_intelligence.workflow import run_product_draft_workflow


@dataclass(frozen=True, slots=True)
class FileWorkerResult:
    job_id: UUID
    status: str
    outcome: str
    ai_task_id: UUID | None = None
    candidate_fields: int = 0
    candidate_status: str | None = None
    candidate_idempotent: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _bind_worker_context(session: Session, tenant_id: UUID) -> None:
    set_request_context(
        session,
        organization_id=UUID(int=0),
        tenant_id=tenant_id,
        user_id=UUID(int=0),
    )


def _source_key(quarantine_key: str) -> str:
    if "/quarantine/" not in quarantine_key:
        raise ValueError("media object is not in the quarantine namespace")
    return quarantine_key.replace("/quarantine/", "/source/", 1)


def _record_retry(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    error: Exception,
    now: datetime,
) -> FileWorkerResult:
    session.rollback()
    _bind_worker_context(session, tenant_id)
    graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
    if graph is None:
        return FileWorkerResult(job_id=job_id, status="FAILED", outcome="JOB_GRAPH_MISSING")
    job, media, source, import_job = graph
    terminal = job.attempt_count >= job.max_attempts
    job.status = "DEAD" if terminal else "RETRY"
    job.available_at = now + timedelta(seconds=min(60, 2 ** max(0, job.attempt_count - 1)))
    job.lease_owner = None
    job.lease_expires_at = None
    job.safe_error_code = "FILE_SECURITY_PIPELINE_ERROR"
    job.safe_error_message = f"File security pipeline failed: {type(error).__name__}."
    media.status = "QUARANTINED"
    media.scan_status = "ERROR"
    media.scan_result = {"code": "SCANNER_OR_STORAGE_ERROR"}
    media.scan_at = now
    source.security_status = "SCAN_ERROR"
    import_job.status = "failed" if terminal else "scanning"
    import_job.error_message = (
        "文件安全检查失败并已停止重试。" if terminal else "文件安全检查暂时失败，等待自动重试。"
    )
    if terminal:
        job.completed_at = now
    session.commit()
    return FileWorkerResult(job_id=job.id, status=job.status, outcome="RETRYABLE_ERROR")


def process_file_worker_job(
    session: Session,
    *,
    tenant_id: UUID,
    job_id: UUID,
    worker_id: str,
    storage: ObjectStoragePort | None = None,
    scanner: FileScannerPort | None = None,
    now: datetime | None = None,
) -> FileWorkerResult:
    storage = storage or get_object_storage()
    scanner = scanner or get_file_scanner()
    now = now or _now()
    _bind_worker_context(session, tenant_id)
    existing = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
    if existing is not None and existing[0].status == "SUCCEEDED":
        checkpoint = existing[0].checkpoint
        return FileWorkerResult(
            job_id=job_id,
            status="SUCCEEDED",
            outcome=str(checkpoint.get("outcome", "ALREADY_COMPLETED")),
            ai_task_id=UUID(checkpoint["ai_task_id"]) if checkpoint.get("ai_task_id") else None,
            candidate_fields=int(checkpoint.get("candidate_fields", 0)),
            candidate_status=checkpoint.get("candidate_status"),
            candidate_idempotent=True,
        )
    claimed = claim_worker_job(
        session,
        tenant_id=tenant_id,
        job_id=job_id,
        now=now,
        worker_id=worker_id,
        lease_expires_at=now + timedelta(seconds=60),
    )
    if claimed is None:
        session.rollback()
        return FileWorkerResult(job_id=job_id, status="NOT_CLAIMED", outcome="NOT_DUE_OR_LEASED")
    session.commit()

    try:
        _bind_worker_context(session, tenant_id)
        graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
        if graph is None:
            raise RuntimeError("worker job graph is incomplete")
        job, media, source, import_job = graph
        media.status = "SCANNING"
        media.scan_status = "RUNNING"
        source.security_status = "SCANNING"
        import_job.status = "scanning"
        import_job.progress = 10
        session.commit()

        with storage.materialize(media.object_key) as quarantine_path:
            scan_result = scanner.scan(quarantine_path)

        _bind_worker_context(session, tenant_id)
        graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
        if graph is None:
            raise RuntimeError("worker job graph disappeared")
        job, media, source, import_job = graph
        media.scan_engine = scan_result.engine
        media.scan_at = now
        if not scan_result.clean:
            media.status = "REJECTED"
            media.scan_status = "INFECTED"
            media.scan_result = {
                "code": scan_result.detail_code,
                "signature": scan_result.signature,
            }
            source.security_status = "QUARANTINED"
            import_job.status = "failed"
            import_job.progress = 100
            import_job.error_message = "文件未通过安全检查，已隔离且不会进入解析流程。"
            import_job.completed_at = now
            job.status = "SUCCEEDED"
            job.checkpoint = {"scan": "INFECTED", "outcome": "QUARANTINED"}
            job.lease_owner = None
            job.lease_expires_at = None
            job.completed_at = now
            session.commit()
            return FileWorkerResult(job_id=job.id, status=job.status, outcome="QUARANTINED")

        source_key = _source_key(media.object_key)
        storage.promote(quarantine_key=media.object_key, source_key=source_key)
        media.object_key = source_key
        media.zone = "SOURCE"
        media.status = "AVAILABLE"
        media.scan_status = "CLEAN"
        media.scan_result = {"code": "CLEAN"}
        source.security_status = "ACCEPTED"
        local_path = storage.local_path(source_key)
        source.local_path = str(local_path) if local_path is not None else ""
        job.checkpoint = {"scan": "CLEAN", "promoted": True}
        session.commit()

        with storage.materialize(source_key) as source_path:
            process_import(
                import_job.id,
                tenant_id=tenant_id,
                source_path=source_path,
            )
            _bind_worker_context(session, tenant_id)
            workflow = run_product_draft_workflow(
                session,
                tenant_id=tenant_id,
                source_file_id=source.id,
                parser=NativeSupplierFileParserAdapter(),
                idempotency_context=f"supplier:{import_job.supplier_id or 'UNASSIGNED'}",
                source_path=source_path,
            )
            session.commit()

        _bind_worker_context(session, tenant_id)
        graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
        if graph is None:
            raise RuntimeError("worker job graph disappeared after parsing")
        job, _media, _source, _import_job = graph
        job.status = "SUCCEEDED" if workflow.status == "NEEDS_REVIEW" else "FAILED"
        job.checkpoint = {
            "scan": "CLEAN",
            "promoted": True,
            "outcome": "PARSED" if workflow.status == "NEEDS_REVIEW" else "PARSE_FAILED",
            "ai_task_id": str(workflow.task_id),
            "candidate_fields": workflow.candidate_fields,
            "candidate_status": workflow.status,
        }
        job.lease_owner = None
        job.lease_expires_at = None
        job.completed_at = now
        session.commit()
        return FileWorkerResult(
            job_id=job.id,
            status=job.status,
            outcome=str(job.checkpoint["outcome"]),
            ai_task_id=workflow.task_id,
            candidate_fields=workflow.candidate_fields,
            candidate_status=workflow.status,
            candidate_idempotent=workflow.idempotent,
        )
    except Exception as exc:
        return _record_retry(
            session,
            tenant_id=tenant_id,
            job_id=job_id,
            error=exc,
            now=now,
        )


def inline_worker_enabled(*, database_dialect: str) -> bool:
    default = "true" if database_dialect == "sqlite" else "false"
    return os.getenv("FILE_WORKER_INLINE", default).lower() in {"1", "true", "yes"}
