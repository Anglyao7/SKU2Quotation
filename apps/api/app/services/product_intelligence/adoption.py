import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ...ai_data_models import AITaskRow
from ...db_models import ImportJobRow
from ...identity_models import MembershipRow
from ...knowledge_embedding_models import KnowledgeDocumentRow
from ...model_mixins import mark_deleted, utcnow
from ...product_intelligence_models import (
    OutboxEventRow,
    ProductCandidateDecisionRow,
    ProductFieldCandidateRow,
)
from ...product_supplier_models import (
    ProductAttributeRow,
    ProductRow,
    ProductVersionRow,
    SupplierProductRow,
)
from ..knowledge import KnowledgeProjectionResult, project_product_knowledge
from .normalization import NORMALIZATION_RULE_VERSION, normalize_product_field


PRODUCT_COMMITTED_EVENT = "product.committed"
PRODUCT_COMMITTED_SCHEMA_VERSION = 1
_CORE_FIELDS = {"name", "description"}
_SUPPLY_FIELDS = {"moq"}
_UNSUPPORTED_FIELDS = {"price", "image"}


class ProductAdoptionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class ProductAdoptionResult:
    decision_id: UUID
    product_id: UUID
    product_version: int
    outbox_event_id: UUID
    outbox_status: str
    idempotent: bool


@dataclass(frozen=True, slots=True)
class ProductRejectionResult:
    decision_id: UUID
    status: str
    idempotent: bool


@dataclass(frozen=True, slots=True)
class ProductProjectionDispatchResult:
    event_id: UUID
    status: str
    attempt_count: int
    document_id: UUID | None
    product_id: UUID
    product_version: int
    idempotent: bool
    error_code: str | None = None


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_rows(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    candidate_group_key: str,
) -> list[ProductFieldCandidateRow]:
    rows = session.scalars(
        select(ProductFieldCandidateRow)
        .where(
            ProductFieldCandidateRow.tenant_id == tenant_id,
            ProductFieldCandidateRow.ai_task_id == task_id,
            ProductFieldCandidateRow.candidate_group_key == candidate_group_key,
        )
        .order_by(ProductFieldCandidateRow.field_key, ProductFieldCandidateRow.id)
    ).all()
    if not rows:
        raise ProductAdoptionError(
            "CANDIDATE_GROUP_NOT_FOUND",
            "Candidate group was not found for this tenant and task.",
        )
    return list(rows)


def _active_reviewer(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
) -> MembershipRow:
    membership = session.scalar(
        select(MembershipRow).where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.id == membership_id,
            MembershipRow.status == "active",
        )
    )
    if membership is None:
        raise ProductAdoptionError(
            "REVIEWER_NOT_ACTIVE",
            "An active membership in the current tenant is required.",
        )
    return membership


def _existing_idempotent_decision(
    session: Session,
    *,
    tenant_id: UUID,
    idempotency_key: str,
) -> ProductCandidateDecisionRow | None:
    return session.scalar(
        select(ProductCandidateDecisionRow).where(
            ProductCandidateDecisionRow.tenant_id == tenant_id,
            ProductCandidateDecisionRow.idempotency_key == idempotency_key,
        )
    )


def _normalization_snapshot(
    rows: list[ProductFieldCandidateRow],
    human_values: dict[str, str],
) -> dict[str, Any]:
    by_key = {row.field_key: row for row in rows}
    unknown = sorted(set(human_values) - set(by_key))
    if unknown:
        raise ProductAdoptionError(
            "UNKNOWN_CANDIDATE_FIELD",
            f"Confirmed values contain unknown candidate fields: {', '.join(unknown)}.",
        )
    if "name" not in human_values:
        raise ProductAdoptionError(
            "PRODUCT_NAME_CONFIRMATION_REQUIRED",
            "A human-confirmed product name is required.",
        )
    unsupported = sorted(set(human_values) & _UNSUPPORTED_FIELDS)
    if unsupported:
        raise ProductAdoptionError(
            "UNSUPPORTED_ADOPTION_FIELD",
            f"Fields require a separate authoritative workflow: {', '.join(unsupported)}.",
        )

    snapshot: dict[str, Any] = {}
    for field_key, human_value in sorted(human_values.items()):
        row = by_key[field_key]
        normalized = normalize_product_field(field_key, human_value)
        if normalized.validation_status == "FAILED":
            raise ProductAdoptionError(
                "FIELD_NORMALIZATION_FAILED",
                f"Confirmed field '{field_key}' did not pass deterministic validation.",
            )
        snapshot[field_key] = {
            "candidate_id": str(row.id),
            "evidence_id": str(row.source_evidence_id),
            "candidate_hash": row.candidate_hash,
            "raw_value": row.raw_value,
            "candidate_normalized_value": row.normalized_value,
            "human_value": human_value.strip(),
            "normalized_value": normalized.value,
            "normalized_unit": normalized.unit,
            "normalization_rule_version": normalized.rule_version,
            "normalization_trace": list(normalized.trace),
            "warnings": list(normalized.warnings),
        }
    if not str(snapshot["name"]["human_value"]).strip():
        raise ProductAdoptionError(
            "PRODUCT_NAME_CONFIRMATION_REQUIRED",
            "A human-confirmed product name is required.",
        )
    return snapshot


def _attribute_key(field_key: str) -> str:
    return "source_category" if field_key == "category" else field_key


def _replace_confirmed_attribute(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
    field_key: str,
    normalized: dict[str, Any],
    unit: str | None,
) -> None:
    attribute_key = _attribute_key(field_key)
    existing = session.scalars(
        select(ProductAttributeRow).where(
            ProductAttributeRow.tenant_id == tenant_id,
            ProductAttributeRow.product_id == product_id,
            ProductAttributeRow.attribute_key == attribute_key,
            ProductAttributeRow.review_status == "CONFIRMED",
        )
    ).all()
    for attribute in existing:
        mark_deleted(attribute)

    value_text: str | None = None
    value_number: Decimal | None = None
    value_json: dict[str, Any] | list[Any] | None = None
    scalar = normalized.get("value")
    if set(normalized).issubset({"value", "unit"}) and scalar is not None:
        if field_key in {"weight", "capacity", "size", "specification"}:
            try:
                value_number = Decimal(str(scalar))
            except InvalidOperation:
                value_text = str(scalar)
        else:
            value_text = str(scalar)
    else:
        value_json = normalized
    session.add(
        ProductAttributeRow(
            tenant_id=tenant_id,
            product_id=product_id,
            attribute_key=attribute_key,
            value_text=value_text,
            value_number=value_number,
            unit_code=unit,
            value_json=value_json,
            confidence=None,
            review_status="CONFIRMED",
        )
    )


def _source_supplier_id(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> str | None:
    task = session.scalar(
        select(AITaskRow).where(AITaskRow.tenant_id == tenant_id, AITaskRow.id == task_id)
    )
    if task is None or task.business_entity_type != "SOURCE_FILE":
        return None
    job = session.scalar(
        select(ImportJobRow)
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.source_file_id == task.business_entity_id,
        )
        .order_by(ImportJobRow.created_at.desc())
    )
    return job.supplier_id if job is not None else None


def _refresh_task_review_status(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
) -> None:
    candidate_groups = int(
        session.scalar(
            select(func.count(distinct(ProductFieldCandidateRow.candidate_group_key))).where(
                ProductFieldCandidateRow.tenant_id == tenant_id,
                ProductFieldCandidateRow.ai_task_id == task_id,
            )
        )
        or 0
    )
    decided_groups = int(
        session.scalar(
            select(func.count(distinct(ProductCandidateDecisionRow.candidate_group_key))).where(
                ProductCandidateDecisionRow.tenant_id == tenant_id,
                ProductCandidateDecisionRow.ai_task_id == task_id,
            )
        )
        or 0
    )
    task = session.scalar(
        select(AITaskRow).where(AITaskRow.tenant_id == tenant_id, AITaskRow.id == task_id)
    )
    if task is not None and candidate_groups > 0 and decided_groups >= candidate_groups:
        task.status = "SUCCEEDED"
        task.progress = 100
        task.completed_at = utcnow()


def _upsert_supplier_product(
    session: Session,
    *,
    tenant_id: UUID,
    supplier_id: str,
    product: ProductRow,
    snapshot: dict[str, Any],
) -> SupplierProductRow:
    model_value = snapshot.get("model", {}).get("normalized_value", {}).get("value")
    supplier_product = session.scalar(
        select(SupplierProductRow)
        .where(
            SupplierProductRow.tenant_id == tenant_id,
            SupplierProductRow.supplier_id == supplier_id,
            SupplierProductRow.product_id == product.id,
        )
        .order_by(SupplierProductRow.created_at.desc())
    )
    if supplier_product is None:
        supplier_product = SupplierProductRow(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            product_id=product.id,
            version=1,
        )
        session.add(supplier_product)
    else:
        supplier_product.version += 1
    supplier_product.supplier_sku = str(model_value).strip() if model_value else None
    supplier_product.supplier_product_name = product.name
    supplier_product.status = "ACTIVE"
    moq = snapshot.get("moq", {}).get("normalized_value")
    if moq:
        supplier_product.moq = Decimal(str(moq["value"]))
        supplier_product.moq_unit = moq.get("unit") or "piece"
    return supplier_product


def _product_snapshot(
    session: Session,
    *,
    tenant_id: UUID,
    product: ProductRow,
) -> dict[str, Any]:
    attributes = session.scalars(
        select(ProductAttributeRow)
        .where(
            ProductAttributeRow.tenant_id == tenant_id,
            ProductAttributeRow.product_id == product.id,
            ProductAttributeRow.review_status == "CONFIRMED",
        )
        .order_by(ProductAttributeRow.attribute_key, ProductAttributeRow.id)
    ).all()
    suppliers = session.scalars(
        select(SupplierProductRow)
        .where(
            SupplierProductRow.tenant_id == tenant_id,
            SupplierProductRow.product_id == product.id,
        )
        .order_by(SupplierProductRow.supplier_id, SupplierProductRow.id)
    ).all()

    def attribute_value(row: ProductAttributeRow) -> Any:
        if row.value_text is not None:
            return row.value_text
        if row.value_number is not None:
            value: Any = format(row.value_number, "f")
            return {"value": value, "unit": row.unit_code} if row.unit_code else value
        if row.value_boolean is not None:
            return row.value_boolean
        return row.value_json

    return _json_value(
        {
            "schema_version": 1,
            "product": {
                "id": product.id,
                "version": product.current_version,
                "product_code": product.product_code,
                "name": product.name,
                "description": product.description,
                "category_id": product.category_id,
                "status": product.status,
                "default_unit": product.default_unit,
            },
            "attributes": [
                {"key": row.attribute_key, "value": attribute_value(row)} for row in attributes
            ],
            "supplier_products": [
                {
                    "supplier_id": row.supplier_id,
                    "supplier_sku": row.supplier_sku,
                    "supplier_product_name": row.supplier_product_name,
                    "moq": row.moq,
                    "moq_unit": row.moq_unit,
                    "lead_time_days": row.lead_time_days,
                    "status": row.status,
                    "version": row.version,
                }
                for row in suppliers
            ],
        }
    )


def _capture_legacy_baseline_if_needed(
    session: Session,
    *,
    tenant_id: UUID,
    product: ProductRow,
    created_by: UUID,
) -> None:
    existing = session.scalar(
        select(ProductVersionRow.id).where(
            ProductVersionRow.tenant_id == tenant_id,
            ProductVersionRow.product_id == product.id,
            ProductVersionRow.version_number == product.current_version,
        )
    )
    if existing is not None:
        return
    snapshot = _product_snapshot(session, tenant_id=tenant_id, product=product)
    session.add(
        ProductVersionRow(
            tenant_id=tenant_id,
            product_id=product.id,
            version_number=product.current_version,
            snapshot=snapshot,
            content_hash=_canonical_hash(snapshot),
            change_reason="Legacy baseline captured before Product Intelligence adoption",
            created_by=created_by,
        )
    )
    session.flush()


def approve_candidate_group(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    candidate_group_key: str,
    reviewer_membership_id: UUID,
    idempotency_key: str,
    confirmed_values: dict[str, str],
    activate: bool,
    target_product_id: UUID | None = None,
    expected_product_version: int | None = None,
    product_code: str | None = None,
    change_reason: str | None = None,
) -> ProductAdoptionResult:
    """Apply a human-reviewed candidate group and enqueue projection in one transaction."""

    existing = _existing_idempotent_decision(
        session, tenant_id=tenant_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        if existing.action != "APPROVE" or existing.product_id is None:
            raise ProductAdoptionError(
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was already used for a different review action.",
            )
        event = session.scalar(
            select(OutboxEventRow).where(
                OutboxEventRow.tenant_id == tenant_id,
                OutboxEventRow.decision_id == existing.id,
            )
        )
        if event is None:
            raise ProductAdoptionError(
                "ADOPTION_EVENT_MISSING",
                "Applied review decision is missing its transactional outbox event.",
            )
        return ProductAdoptionResult(
            decision_id=existing.id,
            product_id=existing.product_id,
            product_version=int(existing.applied_product_version or 0),
            outbox_event_id=event.id,
            outbox_status=event.status,
            idempotent=True,
        )

    prior_approval = session.scalar(
        select(ProductCandidateDecisionRow).where(
            ProductCandidateDecisionRow.tenant_id == tenant_id,
            ProductCandidateDecisionRow.ai_task_id == task_id,
            ProductCandidateDecisionRow.candidate_group_key == candidate_group_key,
            ProductCandidateDecisionRow.action == "APPROVE",
            ProductCandidateDecisionRow.status == "APPLIED",
        )
    )
    if prior_approval is not None:
        raise ProductAdoptionError(
            "CANDIDATE_GROUP_ALREADY_APPLIED",
            "Candidate group already produced an authoritative Product version.",
        )

    reviewer = _active_reviewer(
        session,
        tenant_id=tenant_id,
        membership_id=reviewer_membership_id,
    )
    rows = _candidate_rows(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        candidate_group_key=candidate_group_key,
    )
    snapshot = _normalization_snapshot(rows, confirmed_values)
    supplier_id = _source_supplier_id(session, tenant_id=tenant_id, task_id=task_id)
    if "moq" in snapshot and supplier_id is None:
        raise ProductAdoptionError(
            "SUPPLIER_REQUIRED_FOR_MOQ",
            "MOQ is a SupplierProduct fact and requires a confirmed source supplier.",
        )

    now = utcnow()
    input_hash = _canonical_hash(
        {
            "task_id": task_id,
            "candidate_group_key": candidate_group_key,
            "candidate_hashes": [row.candidate_hash for row in rows],
            "confirmed_values": confirmed_values,
            "target_product_id": target_product_id,
            "expected_product_version": expected_product_version,
            "activate": activate,
            "product_code": product_code,
        }
    )
    decision = ProductCandidateDecisionRow(
        tenant_id=tenant_id,
        ai_task_id=task_id,
        candidate_group_key=candidate_group_key,
        action="APPROVE",
        status="APPLIED",
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        candidate_ids=[str(row.id) for row in rows],
        human_values={key: value.strip() for key, value in confirmed_values.items()},
        normalization_snapshot=snapshot,
        normalization_rule_version=NORMALIZATION_RULE_VERSION,
        reviewed_by_membership_id=reviewer.id,
        expected_product_version=expected_product_version,
        change_reason=change_reason,
        reviewed_at=now,
        applied_at=now,
    )

    if target_product_id is None:
        if expected_product_version is not None:
            raise ProductAdoptionError(
                "UNEXPECTED_PRODUCT_VERSION",
                "Expected Product version is only valid when updating an existing Product.",
            )
        product = ProductRow(
            tenant_id=tenant_id,
            product_code=product_code.strip() if product_code else None,
            name=str(snapshot["name"]["human_value"]),
            description=(
                str(snapshot["description"]["human_value"])
                if "description" in snapshot
                else None
            ),
            status="ACTIVE" if activate else "DRAFT",
            default_unit="piece",
            current_version=1,
            search_document_version=0,
            created_by=reviewer.user_id,
            updated_by=reviewer.user_id,
        )
        session.add(product)
        session.flush()
    else:
        product = session.scalar(
            select(ProductRow).where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.id == target_product_id,
            )
        )
        if product is None:
            raise ProductAdoptionError(
                "TARGET_PRODUCT_NOT_FOUND",
                "Target Product was not found in the current tenant.",
            )
        if expected_product_version is None:
            raise ProductAdoptionError(
                "EXPECTED_PRODUCT_VERSION_REQUIRED",
                "Updating a Product requires its expected current version.",
            )
        if product.current_version != expected_product_version:
            raise ProductAdoptionError(
                "PRODUCT_VERSION_CONFLICT",
                "Product changed after review; reload candidates before applying.",
            )
        _capture_legacy_baseline_if_needed(
            session,
            tenant_id=tenant_id,
            product=product,
            created_by=reviewer.user_id,
        )
        product.current_version += 1
        product.name = str(snapshot["name"]["human_value"])
        if "description" in snapshot:
            product.description = str(snapshot["description"]["human_value"])
        if product_code is not None:
            product.product_code = product_code.strip() or None
        product.status = "ACTIVE" if activate else "DRAFT"
        product.updated_by = reviewer.user_id
        session.flush()

    decision.product_id = product.id
    decision.applied_product_version = product.current_version
    session.add(decision)
    session.flush()
    for field_key, field_snapshot in snapshot.items():
        if field_key in _CORE_FIELDS or field_key in _SUPPLY_FIELDS:
            continue
        _replace_confirmed_attribute(
            session,
            tenant_id=tenant_id,
            product_id=product.id,
            field_key=field_key,
            normalized=field_snapshot["normalized_value"],
            unit=field_snapshot["normalized_unit"],
        )
    if supplier_id is not None:
        _upsert_supplier_product(
            session,
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            product=product,
            snapshot=snapshot,
        )
    session.flush()

    product_snapshot = _product_snapshot(session, tenant_id=tenant_id, product=product)
    primary_evidence_id = next(
        (
            row.source_evidence_id
            for row in rows
            if row.field_key == "name"
        ),
        rows[0].source_evidence_id,
    )
    version = ProductVersionRow(
        tenant_id=tenant_id,
        product_id=product.id,
        version_number=product.current_version,
        snapshot=product_snapshot,
        content_hash=_canonical_hash(product_snapshot),
        change_reason=change_reason or "Human-approved Product Intelligence adoption",
        source_evidence_id=primary_evidence_id,
        review_decision_id=decision.id,
        created_by=reviewer.user_id,
    )
    session.add(version)
    event = OutboxEventRow(
        tenant_id=tenant_id,
        decision_id=decision.id,
        event_type=PRODUCT_COMMITTED_EVENT,
        schema_version=PRODUCT_COMMITTED_SCHEMA_VERSION,
        aggregate_type="PRODUCT",
        aggregate_id=str(product.id),
        aggregate_version=product.current_version,
        payload={
            "product_id": str(product.id),
            "product_version": product.current_version,
            "decision_id": str(decision.id),
            "knowledge_projection_requested": activate,
        },
        correlation_id=str(task_id),
        causation_id=str(decision.id),
        status="PENDING",
        occurred_at=now,
        available_at=now,
    )
    session.add(event)
    session.flush()
    _refresh_task_review_status(session, tenant_id=tenant_id, task_id=task_id)
    session.flush()
    return ProductAdoptionResult(
        decision_id=decision.id,
        product_id=product.id,
        product_version=product.current_version,
        outbox_event_id=event.id,
        outbox_status=event.status,
        idempotent=False,
    )


def reject_candidate_group(
    session: Session,
    *,
    tenant_id: UUID,
    task_id: UUID,
    candidate_group_key: str,
    reviewer_membership_id: UUID,
    idempotency_key: str,
    reason: str,
) -> ProductRejectionResult:
    existing = _existing_idempotent_decision(
        session, tenant_id=tenant_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        if existing.action != "REJECT":
            raise ProductAdoptionError(
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was already used for a different review action.",
            )
        return ProductRejectionResult(
            decision_id=existing.id,
            status=existing.status,
            idempotent=True,
        )
    reviewer = _active_reviewer(
        session,
        tenant_id=tenant_id,
        membership_id=reviewer_membership_id,
    )
    rows = _candidate_rows(
        session,
        tenant_id=tenant_id,
        task_id=task_id,
        candidate_group_key=candidate_group_key,
    )
    now = utcnow()
    decision = ProductCandidateDecisionRow(
        tenant_id=tenant_id,
        ai_task_id=task_id,
        candidate_group_key=candidate_group_key,
        action="REJECT",
        status="RECORDED",
        idempotency_key=idempotency_key,
        input_hash=_canonical_hash(
            {
                "task_id": task_id,
                "candidate_group_key": candidate_group_key,
                "candidate_hashes": [row.candidate_hash for row in rows],
                "reason": reason,
            }
        ),
        candidate_ids=[str(row.id) for row in rows],
        human_values={},
        normalization_snapshot={},
        normalization_rule_version=NORMALIZATION_RULE_VERSION,
        reviewed_by_membership_id=reviewer.id,
        change_reason=reason.strip(),
        reviewed_at=now,
    )
    session.add(decision)
    session.flush()
    _refresh_task_review_status(session, tenant_id=tenant_id, task_id=task_id)
    session.flush()
    return ProductRejectionResult(decision_id=decision.id, status=decision.status, idempotent=False)


def dispatch_product_committed_event(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> ProductProjectionDispatchResult:
    """Process one committed outbox event in a transaction separate from Product adoption."""

    event = session.scalar(
        select(OutboxEventRow).where(
            OutboxEventRow.tenant_id == tenant_id,
            OutboxEventRow.id == event_id,
        ).with_for_update()
    )
    if event is None or event.event_type != PRODUCT_COMMITTED_EVENT:
        raise ProductAdoptionError(
            "PRODUCT_COMMITTED_EVENT_NOT_FOUND",
            "ProductCommitted event was not found for this tenant.",
        )
    product_id = UUID(str(event.payload["product_id"]))
    product_version = int(event.payload["product_version"])
    if event.status == "PUBLISHED":
        document_id = session.scalar(
            select(KnowledgeDocumentRow.id).where(
                KnowledgeDocumentRow.tenant_id == tenant_id,
                KnowledgeDocumentRow.source_entity_id == product_id,
                KnowledgeDocumentRow.source_version == product_version,
                KnowledgeDocumentRow.status == "ACTIVE",
            )
        )
        return ProductProjectionDispatchResult(
            event_id=event.id,
            status=event.status,
            attempt_count=event.attempt_count,
            document_id=document_id,
            product_id=product_id,
            product_version=product_version,
            idempotent=True,
        )

    event.attempt_count += 1
    event.last_error_code = None
    event.last_error_message = None
    if not bool(event.payload.get("knowledge_projection_requested")):
        event.status = "PUBLISHED"
        event.published_at = utcnow()
        session.flush()
        return ProductProjectionDispatchResult(
            event_id=event.id,
            status=event.status,
            attempt_count=event.attempt_count,
            document_id=None,
            product_id=product_id,
            product_version=product_version,
            idempotent=False,
        )

    projection: KnowledgeProjectionResult | None = None
    try:
        with session.begin_nested():
            projection = project_product_knowledge(
                session,
                tenant_id=tenant_id,
                product_id=product_id,
            )
            if projection.source_version != product_version:
                raise ProductAdoptionError(
                    "PRODUCT_VERSION_SUPERSEDED",
                    "ProductCommitted event no longer represents the current Product version.",
                )
    except Exception as exc:
        event.status = "FAILED"
        event.published_at = None
        event.last_error_code = (
            exc.code if isinstance(exc, ProductAdoptionError) else "KNOWLEDGE_PROJECTION_FAILED"
        )
        event.last_error_message = (
            exc.safe_message
            if isinstance(exc, ProductAdoptionError)
            else "Knowledge projection failed; the approved Product version remains committed."
        )
        session.flush()
        return ProductProjectionDispatchResult(
            event_id=event.id,
            status=event.status,
            attempt_count=event.attempt_count,
            document_id=None,
            product_id=product_id,
            product_version=product_version,
            idempotent=False,
            error_code=event.last_error_code,
        )

    event.status = "PUBLISHED"
    event.published_at = utcnow()
    session.flush()
    return ProductProjectionDispatchResult(
        event_id=event.id,
        status=event.status,
        attempt_count=event.attempt_count,
        document_id=projection.document_id if projection else None,
        product_id=product_id,
        product_version=product_version,
        idempotent=False,
    )
