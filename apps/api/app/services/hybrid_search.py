from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import cast, select
from sqlalchemy.orm import Session

from ..knowledge_embedding_models import EmbeddingRow, KnowledgeChunkRow, KnowledgeDocumentRow
from ..product_supplier_models import ProductAttributeRow, ProductRow, SupplierProductRow, SupplierScoreRow
from .embedding import (
    DeterministicFeatureHashEmbedding,
    EmbeddingProvider,
    cosine_similarity,
    normalize_text,
    tokenize,
)


RANKING_VERSION = "hybrid-product-v1"
WEIGHTS = {"keyword": 0.35, "semantic": 0.35, "attribute": 0.20, "supplier": 0.10}


def _score_overlap(query_tokens: set[str], value: str) -> float:
    if not query_tokens:
        return 0.0
    value_tokens = set(tokenize(value))
    return min(1.0, len(query_tokens & value_tokens) / len(query_tokens))


def _as_float_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _semantic_scores(
    session: Session,
    *,
    tenant_id: UUID,
    chunk_ids: list[UUID],
    query_vector: list[float],
    embedder: EmbeddingProvider,
) -> dict[UUID, float]:
    if not chunk_ids:
        return {}
    filters = (
        EmbeddingRow.tenant_id == tenant_id,
        EmbeddingRow.entity_id.in_(chunk_ids),
        EmbeddingRow.model_provider == embedder.identity.provider,
        EmbeddingRow.model_name == embedder.identity.model_name,
        EmbeddingRow.model_version == embedder.identity.model_version,
        EmbeddingRow.dimensions == embedder.identity.dimensions,
        EmbeddingRow.status == "ACTIVE",
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        vector_expression = cast(EmbeddingRow.embedding, VECTOR(embedder.identity.dimensions))
        distance = vector_expression.cosine_distance(query_vector).label("distance")
        rows = session.execute(select(EmbeddingRow.entity_id, distance).where(*filters)).all()
        return {
            entity_id: max(0.0, min(1.0, 1.0 - float(value)))
            for entity_id, value in rows
        }
    rows = session.scalars(select(EmbeddingRow).where(*filters)).all()
    return {
        row.entity_id: max(
            0.0,
            min(1.0, cosine_similarity(query_vector, _as_float_vector(row.embedding))),
        )
        for row in rows
    }


def _attribute_texts(
    session: Session, *, tenant_id: UUID, product_ids: list[UUID]
) -> dict[UUID, str]:
    result: dict[UUID, list[str]] = defaultdict(list)
    if not product_ids:
        return {}
    rows = session.scalars(
        select(ProductAttributeRow).where(
            ProductAttributeRow.tenant_id == tenant_id,
            ProductAttributeRow.product_id.in_(product_ids),
            ProductAttributeRow.review_status == "CONFIRMED",
        )
    ).all()
    for row in rows:
        values: list[Any] = [row.attribute_key, row.value_text, row.value_number, row.value_boolean]
        if row.value_json is not None:
            values.append(row.value_json)
        result[row.product_id].extend(str(value) for value in values if value is not None)
    return {product_id: " ".join(values) for product_id, values in result.items()}


def _supplier_scores(
    session: Session, *, tenant_id: UUID, product_ids: list[UUID]
) -> dict[UUID, tuple[float, str]]:
    if not product_ids:
        return {}
    links = session.scalars(
        select(SupplierProductRow).where(
            SupplierProductRow.tenant_id == tenant_id,
            SupplierProductRow.product_id.in_(product_ids),
            SupplierProductRow.status == "ACTIVE",
        )
    ).all()
    by_product: dict[UUID, list[str]] = defaultdict(list)
    for link in links:
        by_product[link.product_id].append(link.supplier_id)
    supplier_ids = sorted({supplier_id for values in by_product.values() for supplier_id in values})
    if not supplier_ids:
        return {product_id: (0.5, "UNKNOWN") for product_id in product_ids}
    snapshots = session.scalars(
        select(SupplierScoreRow)
        .where(
            SupplierScoreRow.tenant_id == tenant_id,
            SupplierScoreRow.supplier_id.in_(supplier_ids),
        )
        .order_by(SupplierScoreRow.calculated_at.desc())
    ).all()
    latest: dict[str, Decimal | None] = {}
    for snapshot in snapshots:
        latest.setdefault(snapshot.supplier_id, snapshot.overall_score)
    result: dict[UUID, tuple[float, str]] = {}
    for product_id in product_ids:
        known = [latest[supplier_id] for supplier_id in by_product.get(product_id, []) if latest.get(supplier_id) is not None]
        if known:
            result[product_id] = (max(float(score) for score in known) / 100.0, "KNOWN")
        else:
            result[product_id] = (0.5, "UNKNOWN")
    return result


def hybrid_product_search(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    limit: int = 10,
    embedder: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    embedder = embedder or DeterministicFeatureHashEmbedding()
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise ValueError("search query must contain searchable characters")
    query_tokens = set(tokenize(query))
    document_rows = session.execute(
        select(KnowledgeDocumentRow, ProductRow)
        .join(
            ProductRow,
            (ProductRow.tenant_id == KnowledgeDocumentRow.tenant_id)
            & (ProductRow.id == KnowledgeDocumentRow.source_entity_id),
        )
        .where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.status == "ACTIVE",
            KnowledgeDocumentRow.source_entity_type == "PRODUCT",
            ProductRow.status == "ACTIVE",
        )
    ).all()
    if not document_rows:
        return {
            "query": query,
            "ranking_version": RANKING_VERSION,
            "model": _model_payload(embedder),
            "degraded_channels": ["semantic"],
            "results": [],
        }
    document_ids = [document.id for document, _ in document_rows]
    chunks = session.scalars(
        select(KnowledgeChunkRow).where(
            KnowledgeChunkRow.tenant_id == tenant_id,
            KnowledgeChunkRow.document_id.in_(document_ids),
            KnowledgeChunkRow.status == "ACTIVE",
        )
    ).all()
    chunks_by_document: dict[UUID, list[KnowledgeChunkRow]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_document[chunk.document_id].append(chunk)
    query_vector = embedder.embed([query])[0]
    semantic_by_chunk = _semantic_scores(
        session,
        tenant_id=tenant_id,
        chunk_ids=[chunk.id for chunk in chunks],
        query_vector=query_vector,
        embedder=embedder,
    )
    product_ids = [product.id for _, product in document_rows]
    attribute_text = _attribute_texts(session, tenant_id=tenant_id, product_ids=product_ids)
    supplier_scores = _supplier_scores(session, tenant_id=tenant_id, product_ids=product_ids)
    degraded_channels: list[str] = []
    if not semantic_by_chunk:
        degraded_channels.append("semantic")

    ranked: list[tuple[bool, float, dict[str, Any]]] = []
    for document, product in document_rows:
        product_chunks = chunks_by_document.get(document.id, [])
        searchable_text = "\n".join(chunk.content for chunk in product_chunks)
        exact_code = bool(product.product_code) and normalized_query == normalize_text(product.product_code or "")
        keyword = 1.0 if exact_code else _score_overlap(query_tokens, searchable_text)
        attribute = _score_overlap(query_tokens, attribute_text.get(product.id, ""))
        best_chunk = max(
            product_chunks,
            key=lambda chunk: semantic_by_chunk.get(chunk.id, 0.0),
            default=None,
        )
        semantic = semantic_by_chunk.get(best_chunk.id, 0.0) if best_chunk else 0.0
        supplier, supplier_status = supplier_scores.get(product.id, (0.5, "UNKNOWN"))
        final_score = (
            WEIGHTS["keyword"] * keyword
            + WEIGHTS["semantic"] * semantic
            + WEIGHTS["attribute"] * attribute
            + WEIGHTS["supplier"] * supplier
        )
        evidence = []
        if best_chunk is not None:
            evidence.append(
                {
                    "document_id": document.id,
                    "chunk_id": best_chunk.id,
                    "chunk_type": best_chunk.chunk_type,
                    "content_hash": best_chunk.content_hash,
                    "excerpt": best_chunk.content[:240],
                }
            )
        result = {
            "product_id": product.id,
            "product_code": product.product_code,
            "name": product.name,
            "source_version": document.source_version,
            "score": round(final_score, 6),
            "score_breakdown": {
                "keyword": round(keyword, 6),
                "semantic": round(semantic, 6),
                "attribute": round(attribute, 6),
                "supplier": round(supplier, 6),
            },
            "supplier_signal_status": supplier_status,
            "evidence": evidence,
            "ranking_version": RANKING_VERSION,
            "degraded_channels": list(degraded_channels),
        }
        ranked.append((exact_code, final_score, result))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]["product_code"] or ""), reverse=True)
    return {
        "query": query,
        "ranking_version": RANKING_VERSION,
        "model": _model_payload(embedder),
        "degraded_channels": degraded_channels,
        "results": [item[2] for item in ranked[:limit]],
    }


def _model_payload(embedder: EmbeddingProvider) -> dict[str, Any]:
    return {
        "provider": embedder.identity.provider,
        "name": embedder.identity.model_name,
        "version": embedder.identity.model_version,
        "dimensions": embedder.identity.dimensions,
    }
