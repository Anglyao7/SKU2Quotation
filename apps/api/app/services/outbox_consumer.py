from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..knowledge_embedding_models import KnowledgeDocumentRow
from ..model_mixins import utcnow
from ..ports.outbox import OutboxMessage
from ..product_intelligence_models import InboxEventRow, OutboxEventRow
from .knowledge import project_product_knowledge
from .product_intelligence.adoption import (
    PRODUCT_COMMITTED_EVENT,
    ProductAdoptionError,
)


PRODUCT_KNOWLEDGE_CONSUMER = "product-knowledge-projector-v1"


@dataclass(frozen=True, slots=True)
class InboxConsumeResult:
    inbox_id: UUID
    event_id: UUID
    status: str
    idempotent: bool
    document_id: UUID | None = None
    error_code: str | None = None


def consume_product_committed_message(
    session: Session,
    *,
    message: OutboxMessage,
    consumer_name: str = PRODUCT_KNOWLEDGE_CONSUMER,
) -> InboxConsumeResult:
    event = session.scalar(
        select(OutboxEventRow).where(
            OutboxEventRow.tenant_id == message.tenant_id,
            OutboxEventRow.id == message.event_id,
        )
    )
    if event is None or event.event_type != PRODUCT_COMMITTED_EVENT:
        raise ProductAdoptionError(
            "PRODUCT_COMMITTED_EVENT_NOT_FOUND",
            "ProductCommitted event was not found for this tenant.",
        )
    if (
        message.event_type != event.event_type
        or message.schema_version != event.schema_version
        or message.aggregate_type != event.aggregate_type
        or message.aggregate_id != event.aggregate_id
        or message.aggregate_version != event.aggregate_version
        or message.payload != event.payload
    ):
        raise ProductAdoptionError(
            "OUTBOX_MESSAGE_INTEGRITY_FAILED",
            "Delivered event does not match the authoritative Outbox record.",
        )
    product_id = UUID(str(event.payload["product_id"]))
    product_version = int(event.payload["product_version"])

    receipt = session.scalar(
        select(InboxEventRow)
        .where(
            InboxEventRow.tenant_id == message.tenant_id,
            InboxEventRow.consumer_name == consumer_name,
            InboxEventRow.event_id == message.event_id,
        )
        .with_for_update()
    )
    if receipt is not None and receipt.status == "COMPLETED":
        document_id = receipt.result.get("document_id")
        return InboxConsumeResult(
            inbox_id=receipt.id,
            event_id=message.event_id,
            status="COMPLETED",
            idempotent=True,
            document_id=UUID(document_id) if document_id else None,
        )
    if receipt is None:
        candidate_receipt = InboxEventRow(
            tenant_id=message.tenant_id,
            consumer_name=consumer_name,
            event_id=message.event_id,
            event_type=message.event_type,
            status="PROCESSING",
            attempt_count=1,
            result={},
        )
        try:
            with session.begin_nested():
                session.add(candidate_receipt)
                session.flush()
            receipt = candidate_receipt
        except IntegrityError:
            receipt = session.scalar(
                select(InboxEventRow)
                .where(
                    InboxEventRow.tenant_id == message.tenant_id,
                    InboxEventRow.consumer_name == consumer_name,
                    InboxEventRow.event_id == message.event_id,
                )
                .with_for_update()
            )
            if receipt is None:
                raise
            if receipt.status == "COMPLETED":
                document_id = receipt.result.get("document_id")
                return InboxConsumeResult(
                    inbox_id=receipt.id,
                    event_id=message.event_id,
                    status="COMPLETED",
                    idempotent=True,
                    document_id=UUID(document_id) if document_id else None,
                )
    else:
        receipt.status = "PROCESSING"
        receipt.attempt_count += 1
        receipt.last_error_code = None
        receipt.last_error_message = None
        receipt.processed_at = None

    try:
        document_id: UUID | None = None
        if bool(event.payload.get("knowledge_projection_requested")):
            with session.begin_nested():
                projection = project_product_knowledge(
                    session,
                    tenant_id=message.tenant_id,
                    product_id=product_id,
                )
                if projection.source_version != product_version:
                    raise ProductAdoptionError(
                        "PRODUCT_VERSION_SUPERSEDED",
                        "ProductCommitted event no longer represents the current Product version.",
                    )
                document_id = projection.document_id
        else:
            document_id = session.scalar(
                select(KnowledgeDocumentRow.id).where(
                    KnowledgeDocumentRow.tenant_id == message.tenant_id,
                    KnowledgeDocumentRow.source_entity_id == product_id,
                    KnowledgeDocumentRow.source_version == product_version,
                    KnowledgeDocumentRow.status == "ACTIVE",
                )
            )
    except Exception as exc:
        receipt.status = "FAILED"
        receipt.result = {}
        receipt.last_error_code = (
            exc.code if isinstance(exc, ProductAdoptionError) else "EVENT_CONSUMER_FAILED"
        )
        receipt.last_error_message = (
            exc.safe_message
            if isinstance(exc, ProductAdoptionError)
            else "Product knowledge event consumption failed."
        )
        receipt.processed_at = None
        session.flush()
        return InboxConsumeResult(
            inbox_id=receipt.id,
            event_id=message.event_id,
            status="FAILED",
            idempotent=False,
            error_code=receipt.last_error_code,
        )

    receipt.status = "COMPLETED"
    receipt.result = {
        "product_id": str(product_id),
        "product_version": product_version,
        "document_id": str(document_id) if document_id else None,
    }
    receipt.last_error_code = None
    receipt.last_error_message = None
    receipt.processed_at = utcnow()
    session.flush()
    return InboxConsumeResult(
        inbox_id=receipt.id,
        event_id=message.event_id,
        status="COMPLETED",
        idempotent=False,
        document_id=document_id,
    )
