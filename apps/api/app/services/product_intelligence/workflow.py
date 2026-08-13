import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...ai_data_models import AISourceEvidenceRow, AITaskRow
from ...db_models import SourceFileRow
from ...product_intelligence_models import AIRunRow, AITaskStepRow, ProductFieldCandidateRow
from ..file_detection import detect_file_path
from ..parsers import parse_document
from .contracts import (
    NativeField,
    NativeProductRecord,
    ProductParseRequest,
    ProductParserError,
    ProductParserPort,
    require_candidate_only,
)
from .normalization import normalize_product_field


TASK_TYPE = "PRODUCT_DOCUMENT_CANDIDATE_DRAFT"
TASK_VERSION = 1
STEP_KEY = "NATIVE_PARSE_AND_CANDIDATE_DRAFT"
STEP_VERSION = 1


class ProductWorkflowNotFound(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ProductWorkflowResult:
    task_id: UUID
    status: str
    run_id: UUID | None
    candidate_fields: int
    idempotent: bool
    recovered: bool
    error_code: str | None = None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _native_records(
    source_file: SourceFileRow,
    *,
    source_path: Path | None = None,
) -> tuple[NativeProductRecord, ...]:
    if source_file.security_status not in {"ACCEPTED", "LEGACY_ACCEPTED"}:
        raise ProductParserError(
            "SOURCE_FILE_NOT_READY",
            "Source file has not completed intake.",
        )
    path = source_path or Path(source_file.local_path)
    detection = detect_file_path(path, source_file.original_filename)
    if detection.parser not in {"openpyxl", "python-csv"}:
        raise ProductParserError(
            "NATIVE_SUPPLIER_FILE_REQUIRED",
            "Phase 4A-1B accepts only a natively parseable XLSX or CSV source.",
        )
    parsed = parse_document(path, detection)
    records: list[NativeProductRecord] = []
    for candidate_index, record in enumerate(parsed.records):
        sheet = str(record.raw_payload.get("sheet") or "Sheet")
        row = str(record.raw_payload.get("row") or candidate_index + 1)
        group_key = f"{source_file.id}:{sheet}:{row}"
        fields = tuple(
            NativeField(
                key=str(field["key"]),
                raw_value=str(field.get("source") or ""),
                normalized_value=field.get("normalized"),
                confidence=float(field["confidence"]) if field.get("confidence") is not None else None,
                source_location=str(field.get("source_location") or record.location),
            )
            for field in record.fields
        )
        records.append(
            NativeProductRecord(
                candidate_group_key=group_key,
                candidate_index=candidate_index,
                source_location=record.location,
                fields=fields,
            )
        )
    return tuple(records)


def _source_location(value: str) -> dict[str, Any]:
    if "!" in value:
        sheet, cell_range = value.rsplit("!", 1)
        return {"sheet": sheet, "range": cell_range}
    return {"description": value}


def _candidate_count(session: Session, *, tenant_id: UUID, task_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ProductFieldCandidateRow)
            .where(
                ProductFieldCandidateRow.tenant_id == tenant_id,
                ProductFieldCandidateRow.ai_task_id == task_id,
            )
        )
        or 0
    )


def run_product_draft_workflow(
    session: Session,
    *,
    tenant_id: UUID,
    source_file_id: str,
    parser: ProductParserPort,
    idempotency_context: str | None = None,
    source_path: Path | None = None,
) -> ProductWorkflowResult:
    """Run a Candidate-Draft-only pipeline; the caller owns the transaction commit."""

    source_file = session.scalar(
        select(SourceFileRow).where(
            SourceFileRow.tenant_id == tenant_id,
            SourceFileRow.id == source_file_id,
        )
    )
    if source_file is None:
        raise ProductWorkflowNotFound("Source file was not found for this tenant")
    if parser.provider_type not in {"FAKE", "NATIVE"}:
        raise ValueError("Product draft workflow permits only registered FAKE or NATIVE providers")

    input_hash = _canonical_hash(
        {
            "source_scope": idempotency_context or source_file.id,
            "source_hash": source_file.sha256,
            "adapter_key": parser.adapter_key,
            "adapter_version": parser.adapter_version,
            "task_version": TASK_VERSION,
        }
    )
    idempotency_key = f"{TASK_TYPE}:v{TASK_VERSION}:{input_hash}"
    task = session.scalar(
        select(AITaskRow).where(
            AITaskRow.tenant_id == tenant_id,
            AITaskRow.idempotency_key == idempotency_key,
        )
    )
    if task is not None and task.status == "NEEDS_REVIEW":
        successful_run_id = session.scalar(
            select(AIRunRow.id)
            .where(
                AIRunRow.tenant_id == tenant_id,
                AIRunRow.ai_task_id == task.id,
                AIRunRow.status == "SUCCEEDED",
            )
            .order_by(AIRunRow.attempt_number.desc())
        )
        return ProductWorkflowResult(
            task_id=task.id,
            status=task.status,
            run_id=successful_run_id,
            candidate_fields=_candidate_count(session, tenant_id=tenant_id, task_id=task.id),
            idempotent=True,
            recovered=False,
        )

    if task is None:
        task = AITaskRow(
            tenant_id=tenant_id,
            task_type=TASK_TYPE,
            task_version=TASK_VERSION,
            business_entity_type="SOURCE_FILE",
            business_entity_id=source_file.id,
            business_entity_version=1,
            risk_level="L2_DRAFTING",
            status="PENDING",
            progress=0,
            input_schema_version=1,
            input_ref=f"source-file://{source_file.id}",
            input_hash=input_hash,
            policy_snapshot={
                "candidate_only": True,
                "review_required": True,
                "product_write_allowed": False,
            },
            budget_snapshot={"external_calls": 0},
            route_snapshot={
                "adapter_key": parser.adapter_key,
                "adapter_version": parser.adapter_version,
                "provider_type": parser.provider_type,
            },
            idempotency_key=idempotency_key,
        )
        session.add(task)
        session.flush()

    step = session.scalar(
        select(AITaskStepRow).where(
            AITaskStepRow.tenant_id == tenant_id,
            AITaskStepRow.ai_task_id == task.id,
            AITaskStepRow.step_key == STEP_KEY,
            AITaskStepRow.step_version == STEP_VERSION,
        )
    )
    if step is None:
        step = AITaskStepRow(
            tenant_id=tenant_id,
            ai_task_id=task.id,
            step_key=STEP_KEY,
            step_version=STEP_VERSION,
            status="PENDING",
            input_hash=input_hash,
        )
        session.add(step)
        session.flush()

    prior_attempts = int(
        session.scalar(
            select(func.count())
            .select_from(AIRunRow)
            .where(AIRunRow.tenant_id == tenant_id, AIRunRow.ai_task_id == task.id)
        )
        or 0
    )
    recovered = prior_attempts > 0
    now = datetime.now(timezone.utc)
    run = AIRunRow(
        tenant_id=tenant_id,
        ai_task_id=task.id,
        attempt_number=prior_attempts + 1,
        adapter_key=parser.adapter_key,
        adapter_version=parser.adapter_version,
        provider_type=parser.provider_type,
        status="RUNNING",
        input_hash=input_hash,
        started_at=now,
        usage={},
    )
    session.add(run)
    session.flush()
    task.status = "RUNNING"
    task.progress = 10
    task.started_at = task.started_at or now
    task.safe_error_code = None
    task.safe_error_message = None
    step.status = "RUNNING"
    step.attempt_count += 1
    step.last_run_id = run.id
    step.started_at = now
    step.completed_at = None
    step.safe_error_code = None
    step.safe_error_message = None
    session.flush()

    try:
        records = _native_records(source_file, source_path=source_path)
        result = parser.parse(
            ProductParseRequest(
                source_file_id=source_file.id,
                source_hash=source_file.sha256,
                records=records,
            )
        )
        require_candidate_only(result)
    except Exception as exc:
        if isinstance(exc, ProductParserError):
            error_code = exc.code
            error_message = exc.safe_message
        else:
            error_code = "PRODUCT_DRAFT_PIPELINE_FAILURE"
            error_message = "The product draft pipeline failed before a complete candidate set was stored."
        completed_at = datetime.now(timezone.utc)
        run.status = "FAILED"
        run.safe_error_code = error_code
        run.safe_error_message = error_message
        run.completed_at = completed_at
        run.duration_ms = max(0, int((completed_at - now).total_seconds() * 1000))
        step.status = "FAILED"
        step.safe_error_code = error_code
        step.safe_error_message = error_message
        step.completed_at = completed_at
        task.status = "PARTIAL"
        task.progress = 10
        task.safe_error_code = error_code
        task.safe_error_message = error_message
        session.flush()
        return ProductWorkflowResult(
            task_id=task.id,
            status=task.status,
            run_id=run.id,
            candidate_fields=0,
            idempotent=False,
            recovered=recovered,
            error_code=error_code,
        )

    candidate_hashes: list[str] = []
    candidate_fields = 0
    for candidate in result.candidates:
        for field in candidate.fields:
            normalized = normalize_product_field(field.field_key, field.raw_value)
            combined_warnings = tuple(dict.fromkeys((*field.warnings, *normalized.warnings)))
            validation_status = field.validation_status
            if normalized.validation_status == "FAILED" or field.validation_status == "FAILED":
                validation_status = "FAILED"
            elif combined_warnings:
                validation_status = "WARNING"
            raw_hash = _canonical_hash(field.raw_value)
            location = _source_location(field.source_location)
            evidence_hash = _canonical_hash(
                {
                    "task_id": task.id,
                    "source_file_id": source_file.id,
                    "location": location,
                    "field_key": field.field_key,
                    "raw_hash": raw_hash,
                }
            )
            evidence = AISourceEvidenceRow(
                tenant_id=tenant_id,
                ai_task_id=task.id,
                source_file_id=source_file.id,
                source_entity_type="SOURCE_FILE",
                source_entity_id=source_file.id,
                source_version=1,
                location_type="SHEET_CELL_RANGE",
                location=location,
                raw_value_ref=f"source-file://{source_file.id}#{field.source_location}",
                raw_value_hash=raw_hash,
                normalized_value_ref=(
                    f"candidate-draft://{task.id}/{candidate.candidate_group_key}/{field.field_key}"
                ),
                claim_summary=f"Candidate field '{field.field_key}' extracted for human review",
                classification="INTERNAL",
                permission_scope={"tenant_id": str(tenant_id)},
                parser_identifier=parser.adapter_key,
                parser_version=parser.adapter_version,
                confidence=(Decimal(str(field.confidence)) if field.confidence is not None else None),
                evidence_hash=evidence_hash,
            )
            session.add(evidence)
            session.flush()
            candidate_hash = _canonical_hash(
                {
                    "group": candidate.candidate_group_key,
                    "field": field.field_key,
                    "raw": field.raw_value,
                    "normalized": normalized.value,
                    "normalization_rule_version": normalized.rule_version,
                    "evidence_hash": evidence_hash,
                }
            )
            session.add(
                ProductFieldCandidateRow(
                    tenant_id=tenant_id,
                    ai_task_id=task.id,
                    ai_run_id=run.id,
                    source_evidence_id=evidence.id,
                    candidate_group_key=candidate.candidate_group_key,
                    candidate_index=candidate.candidate_index,
                    field_key=field.field_key,
                    raw_value=field.raw_value,
                    normalized_value=normalized.value,
                    normalized_unit=normalized.unit,
                    confidence=(
                        Decimal(str(field.confidence)) if field.confidence is not None else None
                    ),
                    confidence_policy_version=1,
                    extractor_key=parser.adapter_key,
                    extractor_version=parser.adapter_version,
                    validation_status=validation_status,
                    review_status=candidate.review_status,
                    warnings=list(combined_warnings),
                    normalization_rule_version=normalized.rule_version,
                    normalization_trace=list(normalized.trace),
                    candidate_hash=candidate_hash,
                )
            )
            candidate_hashes.append(candidate_hash)
            candidate_fields += 1

    completed_at = datetime.now(timezone.utc)
    output_hash = _canonical_hash(candidate_hashes)
    output_ref = f"candidate-draft://{task.id}"
    run.status = "SUCCEEDED"
    run.output_ref = output_ref
    run.output_hash = output_hash
    run.completed_at = completed_at
    run.duration_ms = max(0, int((completed_at - now).total_seconds() * 1000))
    step.status = "SUCCEEDED"
    step.output_ref = output_ref
    step.output_hash = output_hash
    step.completed_at = completed_at
    task.status = "NEEDS_REVIEW"
    task.progress = 100
    task.completed_at = completed_at
    session.flush()
    return ProductWorkflowResult(
        task_id=task.id,
        status=task.status,
        run_id=run.id,
        candidate_fields=candidate_fields,
        idempotent=False,
        recovered=recovered,
    )
