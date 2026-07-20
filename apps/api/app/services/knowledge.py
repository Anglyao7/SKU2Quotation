import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db_models import SupplierRow
from ..knowledge_embedding_models import EmbeddingRow, KnowledgeChunkRow, KnowledgeDocumentRow
from ..model_mixins import utcnow
from ..product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductRow,
    SupplierProductRow,
    SupplierScoreRow,
)
from .embedding import DeterministicFeatureHashEmbedding, EmbeddingProvider, validate_vectors


SCHEMA_VERSION = 1
FIELD_POLICY_VERSION = 1
LOCALE = "und"
FEATURE_MARKERS = ("feature", "use", "application", "cert", "特点", "用途", "认证")
MARKET_MARKERS = ("market", "country", "region", "市场", "国家", "地区")


class KnowledgeProjectionError(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeProjectionResult:
    document_id: UUID
    product_id: UUID
    source_version: int
    chunks: int
    embeddings: int
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int
    idempotent: bool


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _attribute_value(attribute: ProductAttributeRow) -> Any:
    if attribute.value_text is not None:
        return attribute.value_text
    if attribute.value_number is not None:
        value: Any = format(attribute.value_number, "f")
        if attribute.unit_code:
            value = {"value": value, "unit": attribute.unit_code}
        return value
    if attribute.value_boolean is not None:
        return attribute.value_boolean
    return _json_value(attribute.value_json)


def _latest_supplier_scores(
    session: Session, *, tenant_id: UUID, supplier_ids: list[str]
) -> dict[str, dict[str, Any]]:
    if not supplier_ids:
        return {}
    rows = session.scalars(
        select(SupplierScoreRow)
        .where(
            SupplierScoreRow.tenant_id == tenant_id,
            SupplierScoreRow.supplier_id.in_(supplier_ids),
        )
        .order_by(SupplierScoreRow.calculated_at.desc())
    ).all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.supplier_id not in latest:
            latest[row.supplier_id] = {
                "overall_score": _json_value(row.overall_score),
                "method_version": row.method_version,
                "calculated_at": row.calculated_at.isoformat(),
            }
    return latest


def build_product_payload(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> tuple[ProductRow, dict[str, Any]]:
    product = session.scalar(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id == product_id,
            ProductRow.status == "ACTIVE",
        )
    )
    if product is None:
        raise KnowledgeProjectionError("active product not found in tenant")

    category = None
    if product.category_id:
        category = session.scalar(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id == product.category_id,
                ProductCategoryRow.status == "ACTIVE",
            )
        )
    attributes = session.scalars(
        select(ProductAttributeRow)
        .where(
            ProductAttributeRow.tenant_id == tenant_id,
            ProductAttributeRow.product_id == product.id,
            ProductAttributeRow.review_status == "CONFIRMED",
        )
        .order_by(ProductAttributeRow.attribute_key, ProductAttributeRow.id)
    ).all()
    supplier_rows = session.execute(
        select(SupplierProductRow, SupplierRow)
        .join(
            SupplierRow,
            (SupplierRow.tenant_id == SupplierProductRow.tenant_id)
            & (SupplierRow.id == SupplierProductRow.supplier_id),
        )
        .where(
            SupplierProductRow.tenant_id == tenant_id,
            SupplierProductRow.product_id == product.id,
            SupplierProductRow.status == "ACTIVE",
            SupplierRow.status == "ACTIVE",
        )
        .order_by(SupplierProductRow.supplier_id)
    ).all()
    supplier_ids = [supplier_product.supplier_id for supplier_product, _ in supplier_rows]
    latest_scores = _latest_supplier_scores(
        session, tenant_id=tenant_id, supplier_ids=supplier_ids
    )

    payload = {
        "entity": {
            "type": "PRODUCT",
            "id": str(product.id),
            "version": product.current_version,
        },
        "product": {
            "code": product.product_code,
            "name": product.name,
            "description": product.description,
            "default_unit": product.default_unit,
        },
        "category": (
            {
                "id": str(category.id),
                "code": category.code,
                "name": category.name,
                "path": category.path,
            }
            if category
            else None
        ),
        "attributes": [
            {"key": attribute.attribute_key, "value": _attribute_value(attribute)}
            for attribute in attributes
        ],
        "suppliers": [
            {
                "id": supplier.id,
                "code": supplier.supplier_code,
                "name": supplier.name,
                "supplier_sku": supplier_product.supplier_sku,
                "moq": _json_value(supplier_product.moq),
                "moq_unit": supplier_product.moq_unit,
                "lead_time_days": supplier_product.lead_time_days,
                "score": latest_scores.get(supplier.id),
            }
            for supplier_product, supplier in supplier_rows
        ],
        "projection": {
            "schema_version": SCHEMA_VERSION,
            "field_policy_version": FIELD_POLICY_VERSION,
        },
    }
    return product, _json_value(payload)


def _render_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}: {_render_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(_render_value(item) for item in value)
    if value is None:
        return ""
    return str(value)


def build_product_chunks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    product = payload["product"]
    category = payload.get("category") or {}
    overview_lines = [
        f"Product code: {product.get('code') or ''}",
        f"Product name: {product.get('name') or ''}",
        f"Category: {category.get('name') or ''}",
        f"Description: {product.get('description') or ''}",
    ]
    sections: dict[str, list[str]] = {
        "OVERVIEW": [line for line in overview_lines if not line.endswith(": ")],
        "SPECIFICATIONS": [],
        "FEATURES": [],
        "MARKETS": [],
        "SUPPLY": [],
    }
    for attribute in payload.get("attributes", []):
        key = str(attribute["key"])
        line = f"{key}: {_render_value(attribute['value'])}"
        lowered = key.casefold()
        if any(marker in lowered for marker in FEATURE_MARKERS):
            sections["FEATURES"].append(line)
        elif any(marker in lowered for marker in MARKET_MARKERS):
            sections["MARKETS"].append(line)
        else:
            sections["SPECIFICATIONS"].append(line)
    for supplier in payload.get("suppliers", []):
        details = [
            f"supplier={supplier['name']}",
            f"supplier_code={supplier['code']}",
        ]
        if supplier.get("supplier_sku"):
            details.append(f"supplier_sku={supplier['supplier_sku']}")
        if supplier.get("moq") is not None:
            details.append(f"moq={supplier['moq']} {supplier.get('moq_unit') or ''}".strip())
        if supplier.get("lead_time_days") is not None:
            details.append(f"lead_time_days={supplier['lead_time_days']}")
        sections["SUPPLY"].append("; ".join(details))

    chunks: list[dict[str, Any]] = []
    for chunk_type in ("OVERVIEW", "SPECIFICATIONS", "FEATURES", "MARKETS", "SUPPLY"):
        lines = sections[chunk_type]
        if not lines:
            continue
        content = "\n".join(lines)
        chunks.append(
            {
                "chunk_index": len(chunks),
                "chunk_type": chunk_type,
                "section_path": f"product/{chunk_type.casefold()}",
                "content": content,
                "content_hash": _sha256(content),
                "token_count": len(content.split()),
                "metadata": {"source": "Product Center", "field_policy_version": FIELD_POLICY_VERSION},
            }
        )
    return chunks


def project_product_knowledge(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
    embedder: EmbeddingProvider | None = None,
) -> KnowledgeProjectionResult:
    embedder = embedder or DeterministicFeatureHashEmbedding()
    product, payload = build_product_payload(session, tenant_id=tenant_id, product_id=product_id)
    content_hash = _sha256(_stable_json(payload))
    existing = session.scalar(
        select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.source_entity_type == "PRODUCT",
            KnowledgeDocumentRow.source_entity_id == product.id,
            KnowledgeDocumentRow.source_version == product.current_version,
            KnowledgeDocumentRow.schema_version == SCHEMA_VERSION,
            KnowledgeDocumentRow.field_policy_version == FIELD_POLICY_VERSION,
            KnowledgeDocumentRow.locale == LOCALE,
            KnowledgeDocumentRow.content_hash == content_hash,
            KnowledgeDocumentRow.status == "ACTIVE",
        )
    )
    if existing is not None:
        chunk_ids = session.scalars(
            select(KnowledgeChunkRow.id).where(
                KnowledgeChunkRow.tenant_id == tenant_id,
                KnowledgeChunkRow.document_id == existing.id,
                KnowledgeChunkRow.status == "ACTIVE",
            )
        ).all()
        embedding_count = 0
        if chunk_ids:
            embedding_count = session.scalar(
                select(func.count())
                .select_from(EmbeddingRow)
                .where(
                    EmbeddingRow.tenant_id == tenant_id,
                    EmbeddingRow.entity_id.in_(chunk_ids),
                    EmbeddingRow.status == "ACTIVE",
                )
            ) or 0
        return KnowledgeProjectionResult(
            document_id=existing.id,
            product_id=product.id,
            source_version=product.current_version,
            chunks=len(chunk_ids),
            embeddings=int(embedding_count),
            model_provider=embedder.identity.provider,
            model_name=embedder.identity.model_name,
            model_version=embedder.identity.model_version,
            dimensions=embedder.identity.dimensions,
            idempotent=True,
        )

    now = utcnow()
    active_document_ids = session.scalars(
        select(KnowledgeDocumentRow.id).where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.source_entity_type == "PRODUCT",
            KnowledgeDocumentRow.source_entity_id == product.id,
            KnowledgeDocumentRow.locale == LOCALE,
            KnowledgeDocumentRow.status == "ACTIVE",
        )
    ).all()
    if active_document_ids:
        active_chunk_ids = session.scalars(
            select(KnowledgeChunkRow.id).where(
                KnowledgeChunkRow.tenant_id == tenant_id,
                KnowledgeChunkRow.document_id.in_(active_document_ids),
                KnowledgeChunkRow.status == "ACTIVE",
            )
        ).all()
        if active_chunk_ids:
            session.execute(
                update(EmbeddingRow)
                .where(
                    EmbeddingRow.tenant_id == tenant_id,
                    EmbeddingRow.entity_id.in_(active_chunk_ids),
                    EmbeddingRow.status == "ACTIVE",
                )
                .values(status="STALE", superseded_at=now, updated_at=now)
            )
        session.execute(
            update(KnowledgeChunkRow)
            .where(
                KnowledgeChunkRow.tenant_id == tenant_id,
                KnowledgeChunkRow.document_id.in_(active_document_ids),
                KnowledgeChunkRow.status == "ACTIVE",
            )
            .values(status="STALE", updated_at=now)
        )
        session.execute(
            update(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.tenant_id == tenant_id,
                KnowledgeDocumentRow.id.in_(active_document_ids),
                KnowledgeDocumentRow.status == "ACTIVE",
            )
            .values(status="STALE", updated_at=now)
        )
        session.flush()

    document = KnowledgeDocumentRow(
        tenant_id=tenant_id,
        source_entity_type="PRODUCT",
        source_entity_id=product.id,
        source_version=product.current_version,
        title=product.name,
        locale=LOCALE,
        schema_version=SCHEMA_VERSION,
        field_policy_version=FIELD_POLICY_VERSION,
        canonical_payload=payload,
        content_hash=content_hash,
        classification="INTERNAL",
        permission_scope={"modules": ["PRODUCT_CENTER", "AI_INQUIRY"]},
        status="ACTIVE",
    )
    session.add(document)
    session.flush()

    chunk_payloads = build_product_chunks(payload)
    chunks = [
        KnowledgeChunkRow(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=chunk["chunk_index"],
            chunk_type=chunk["chunk_type"],
            section_path=chunk["section_path"],
            content=chunk["content"],
            content_hash=chunk["content_hash"],
            token_count=chunk["token_count"],
            locale=LOCALE,
            chunk_metadata=chunk["metadata"],
            permission_scope=document.permission_scope,
            status="ACTIVE",
        )
        for chunk in chunk_payloads
    ]
    session.add_all(chunks)
    session.flush()
    vectors = embedder.embed([chunk.content for chunk in chunks])
    validate_vectors(
        vectors,
        expected_count=len(chunks),
        dimensions=embedder.identity.dimensions,
    )
    embeddings = [
        EmbeddingRow(
            tenant_id=tenant_id,
            entity_type="KNOWLEDGE_CHUNK",
            entity_id=chunk.id,
            entity_version=chunk.record_version,
            embedding_type="KNOWLEDGE_CHUNK",
            model_provider=embedder.identity.provider,
            model_name=embedder.identity.model_name,
            model_version=embedder.identity.model_version,
            dimensions=embedder.identity.dimensions,
            distance_metric=embedder.identity.distance_metric,
            content_hash=chunk.content_hash,
            embedding=vector,
            permission_scope=chunk.permission_scope,
            status="ACTIVE",
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    session.add_all(embeddings)
    product.search_document_version = product.current_version
    session.flush()
    return KnowledgeProjectionResult(
        document_id=document.id,
        product_id=product.id,
        source_version=product.current_version,
        chunks=len(chunks),
        embeddings=len(embeddings),
        model_provider=embedder.identity.provider,
        model_name=embedder.identity.model_name,
        model_version=embedder.identity.model_version,
        dimensions=embedder.identity.dimensions,
        idempotent=False,
    )
