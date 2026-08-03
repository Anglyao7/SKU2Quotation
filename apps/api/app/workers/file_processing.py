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
from ..services.product_template_import import process_product_template_import
from ..services.product_intelligence.native_parser import NativeSupplierFileParserAdapter
from ..services.product_intelligence.workflow import run_product_draft_workflow


MAX_PERSISTED_TEMPLATE_WARNINGS = 1_000


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
    promoted = bool(job.checkpoint.get("promoted")) and media.zone == "SOURCE"
    template_snapshot_committed = (
        import_job.source_type == "PRODUCT_TEMPLATE"
        and (
            import_job.status == "published"
            or bool(job.checkpoint.get("template_snapshot_committed"))
        )
    )
    job.status = "DEAD" if terminal else "RETRY"
    job.available_at = now + timedelta(seconds=min(60, 2 ** max(0, job.attempt_count - 1)))
    job.lease_owner = None
    job.lease_expires_at = None
    job.safe_error_code = (
        "FILE_IMPORT_PIPELINE_ERROR" if promoted else "FILE_SECURITY_PIPELINE_ERROR"
    )
    job.safe_error_message = (
        f"File import pipeline failed: {type(error).__name__}."
        if promoted
        else f"File security pipeline failed: {type(error).__name__}."
    )
    checkpoint = dict(job.checkpoint)
    checkpoint["last_error_stage"] = "IMPORT" if promoted else "SECURITY"
    checkpoint["last_error_type"] = type(error).__name__
    if template_snapshot_committed:
        checkpoint["template_snapshot_committed"] = True
    job.checkpoint = checkpoint
    if promoted:
        # The quarantine object has already been moved. Preserve the accepted
        # source checkpoint so a retry resumes parsing that durable source
        # object instead of attempting a second promotion.
        media.status = "AVAILABLE"
        media.scan_status = "CLEAN"
        source.security_status = "ACCEPTED"
        if template_snapshot_committed:
            # The template service commits its authoritative data and
            # published status atomically in a separate transaction. A later
            # worker-checkpoint failure must never make that applied snapshot
            # invisible to stale-job protection.
            import_job.status = "published"
            import_job.progress = 100
        else:
            import_job.status = "failed" if terminal else "parsing"
            import_job.error_message = (
                "文件导入处理失败并已停止重试。"
                if terminal
                else "文件导入处理暂时失败，将从已通过检查的源文件自动重试。"
            )
    else:
        media.status = "QUARANTINED"
        media.scan_status = "ERROR"
        media.scan_result = {"code": "SCANNER_OR_STORAGE_ERROR"}
        media.scan_at = now
        source.security_status = "SCAN_ERROR"
        import_job.status = "failed" if terminal else "scanning"
        import_job.error_message = (
            "文件安全检查失败并已停止重试。"
            if terminal
            else "文件安全检查暂时失败，等待自动重试。"
        )
    if terminal:
        job.completed_at = now
        if not template_snapshot_committed:
            import_job.progress = 100
            import_job.completed_at = now
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
        already_promoted = (
            bool(job.checkpoint.get("promoted"))
            and media.zone == "SOURCE"
            and media.scan_status == "CLEAN"
            and source.security_status == "ACCEPTED"
        )
        if already_promoted:
            source_key = media.object_key
            import_job.status = "parsing"
            import_job.progress = max(import_job.progress, 20)
            session.commit()
        else:
            quarantine_key = media.object_key
            expected_source_key = _source_key(quarantine_key)
            recovered_promotion = (
                not storage.exists(quarantine_key)
                and storage.exists(expected_source_key)
            )
            scan_key = expected_source_key if recovered_promotion else quarantine_key
            media.status = "SCANNING"
            media.scan_status = "RUNNING"
            source.security_status = "SCANNING"
            import_job.status = "scanning"
            import_job.progress = 10
            session.commit()

            with storage.materialize(scan_key) as scan_path:
                scan_result = scanner.scan(scan_path)

            _bind_worker_context(session, tenant_id)
            graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
            if graph is None:
                raise RuntimeError("worker job graph disappeared")
            job, media, source, import_job = graph
            media.scan_engine = scan_result.engine
            media.scan_at = now
            if not scan_result.clean:
                if recovered_promotion:
                    # The object moved before the previous checkpoint, but it
                    # has now failed the repeated scan. Move it physically
                    # back to quarantine so the namespace and DB state agree.
                    storage.promote(
                        quarantine_key=expected_source_key,
                        source_key=quarantine_key,
                    )
                    media.object_key = quarantine_key
                    media.zone = "QUARANTINE"
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
                checkpoint = dict(job.checkpoint)
                checkpoint.update({
                    "scan": "INFECTED",
                    "outcome": "QUARANTINED",
                    "promotion_recovered": recovered_promotion,
                })
                job.checkpoint = checkpoint
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = now
                session.commit()
                return FileWorkerResult(job_id=job.id, status=job.status, outcome="QUARANTINED")

            source_key = expected_source_key
            if not recovered_promotion:
                storage.promote(
                    quarantine_key=quarantine_key,
                    source_key=source_key,
                )
            media.object_key = source_key
            media.zone = "SOURCE"
            media.status = "AVAILABLE"
            media.scan_status = "CLEAN"
            media.scan_result = {"code": "CLEAN"}
            source.security_status = "ACCEPTED"
            local_path = storage.local_path(source_key)
            source.local_path = str(local_path) if local_path is not None else ""
            job.checkpoint = {
                "scan": "CLEAN",
                "promoted": True,
                "promotion_recovered": recovered_promotion,
            }
            session.commit()

        with storage.materialize(source_key) as source_path:
            if import_job.source_type == "PRODUCT_TEMPLATE":
                template_result = process_product_template_import(
                    import_job.id,
                    tenant_id=tenant_id,
                    source_path=source_path,
                )
                _bind_worker_context(session, tenant_id)
                graph = load_file_job_graph(session, tenant_id=tenant_id, job_id=job_id)
                if graph is None:
                    raise RuntimeError("worker job graph disappeared after template import")
                job, _media, _source, _import_job = graph
                outcome = {
                    "published": "TEMPLATE_IMPORTED",
                    "superseded": "TEMPLATE_SUPERSEDED",
                }.get(template_result.status, "TEMPLATE_REJECTED")
                all_warnings = list(template_result.warnings)
                issue_details = [
                    issue.as_dict() for issue in template_result.issues
                ]
                persisted_warnings = all_warnings[:MAX_PERSISTED_TEMPLATE_WARNINGS]
                summary_warnings: list[str] = []
                for warning in all_warnings:
                    if warning not in summary_warnings:
                        summary_warnings.append(warning)
                    if len(summary_warnings) == 3:
                        break
                summary_parts = [
                    template_result.message,
                    *summary_warnings,
                ]
                if len(all_warnings) > len(summary_warnings):
                    summary_parts.append(
                        f"另有 {len(all_warnings) - len(summary_warnings)} 条提醒，请查看导入详情。"
                    )
                _import_job.error_message = "；".join(
                    dict.fromkeys(part for part in summary_parts if part)
                )
                job.status = "SUCCEEDED"
                checkpoint = dict(job.checkpoint)
                checkpoint.update({
                    "scan": "CLEAN",
                    "promoted": True,
                    "outcome": outcome,
                    "imported": template_result.imported,
                    "created": template_result.created,
                    "updated": template_result.updated,
                    "unchanged": template_result.unchanged,
                    "skipped": template_result.skipped,
                    "message": template_result.message,
                    "warnings": persisted_warnings,
                    "warning_total": len(all_warnings),
                    "issues": issue_details,
                    "issue_total": len(issue_details),
                    "import_progress": 100,
                    "processed_rows": (
                        template_result.imported + template_result.skipped
                    ),
                    "total_rows": (
                        template_result.imported + template_result.skipped
                    ),
                    "import_stage": (
                        "COMPLETED"
                        if template_result.status == "published"
                        else "VALIDATION_FAILED"
                        if issue_details
                        else "FAILED"
                    ),
                })
                truncated_warning_count = len(all_warnings) - len(persisted_warnings)
                if truncated_warning_count:
                    checkpoint["warnings_truncated"] = truncated_warning_count
                else:
                    checkpoint.pop("warnings_truncated", None)
                job.checkpoint = checkpoint
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = now
                session.commit()
                return FileWorkerResult(
                    job_id=job.id,
                    status=job.status,
                    outcome=outcome,
                )

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
        checkpoint = dict(job.checkpoint)
        checkpoint.update({
            "scan": "CLEAN",
            "promoted": True,
            "outcome": "PARSED" if workflow.status == "NEEDS_REVIEW" else "PARSE_FAILED",
            "ai_task_id": str(workflow.task_id),
            "candidate_fields": workflow.candidate_fields,
            "candidate_status": workflow.status,
        })
        job.checkpoint = checkpoint
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
