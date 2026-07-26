from collections import Counter, defaultdict
from collections.abc import Collection
from decimal import Decimal
import math
import re
from typing import Any
import unicodedata
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import cast, select
from sqlalchemy.orm import Session

from ..knowledge_embedding_models import EmbeddingRow, KnowledgeChunkRow, KnowledgeDocumentRow
from ..product_center_models import SkuRow
from ..product_supplier_models import ProductAttributeRow, ProductRow, SupplierProductRow, SupplierScoreRow
from ..public_catalog_models import PublicCatalogOfferRow
from .embedding import (
    EmbeddingProvider,
    cosine_similarity,
    normalize_text,
)
from .embedding_configuration import resolved_text_embedding_provider


RANKING_VERSION = "hybrid-product-v2"
WEIGHTS = {
    "keyword": 0.32,
    "semantic": 0.45,
    "attribute": 0.06,
    "tag": 0.12,
    "supplier": 0.05,
}
MINIMUM_RESULT_SCORE = 0.20
RELATIVE_RESULT_FLOOR = 0.78
SEARCH_SEGMENT_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)
SINGLE_CHARACTER_STOPWORDS = {"的", "了", "和", "与", "及", "或", "一", "个", "款"}
QUERY_NOISE_PHRASES = (
    "我想找",
    "帮我找",
    "有没有",
    "一盒完成",
    "一盒",
    "支持",
    "适合",
    "需要",
    "可以",
    "多功能",
    "以及",
    "的",
    "和",
    "与",
)


def _retrieval_tokens(value: str, *, query: bool = False) -> set[str]:
    """Tokenize Latin words and Chinese phrases without noisy single-character overlap."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    if query:
        for phrase in QUERY_NOISE_PHRASES:
            normalized = normalized.replace(phrase, " ")
    tokens: set[str] = set()
    for segment in SEARCH_SEGMENT_PATTERN.findall(normalized):
        if segment.isascii():
            tokens.add(segment)
            continue
        if len(segment) == 1:
            if segment not in SINGLE_CHARACTER_STOPWORDS:
                tokens.add(segment)
            continue
        if len(segment) <= 8:
            tokens.add(segment)
        for width in (2, 3):
            tokens.update(
                segment[index : index + width]
                for index in range(len(segment) - width + 1)
            )
    return tokens


def _score_overlap(query_tokens: set[str], value: str) -> float:
    if not query_tokens:
        return 0.0
    value_tokens = _retrieval_tokens(value)
    return min(1.0, len(query_tokens & value_tokens) / len(query_tokens))


def _weighted_query_overlap(
    query_tokens: set[str],
    value_tokens: set[str],
    *,
    document_frequency: Counter[str],
    document_count: int,
) -> float:
    searchable_query_tokens = {
        token for token in query_tokens if document_frequency.get(token, 0) > 0
    }
    if not searchable_query_tokens:
        return 0.0
    weights = {
        token: (
            1.0 + math.log((document_count + 1) / (document_frequency[token] + 1))
        ) * min(1.6, 0.7 + len(token) * 0.3)
        for token in searchable_query_tokens
    }
    total_weight = sum(weights.values())
    if total_weight <= 0:
        return 0.0
    matched_weight = sum(
        weight for token, weight in weights.items() if token in value_tokens
    )
    return min(1.0, matched_weight / total_weight)


def _compact_search_text(value: str) -> str:
    return "".join(SEARCH_SEGMENT_PATTERN.findall(
        unicodedata.normalize("NFKC", value).casefold()
    ))


def _score_tag_relevance(query: str, query_tokens: set[str], tags: list[str]) -> float:
    if not tags:
        return 0.0
    compact_query = _compact_search_text(query)
    query_characters = {character for character in compact_query if "\u4e00" <= character <= "\u9fff"}
    best = 0.0
    for tag in tags:
        compact_tag = _compact_search_text(tag)
        if not compact_tag:
            continue
        if compact_tag == compact_query:
            return 1.0
        if compact_tag in compact_query:
            containment_weight = min(1.0, len(compact_tag) / max(1, len(compact_query)) * 2)
            best = max(best, 0.55 + 0.40 * containment_weight)
        elif compact_query in compact_tag:
            best = max(best, 0.90)
        tag_tokens = _retrieval_tokens(tag)
        if tag_tokens:
            token_coverage = len(query_tokens & tag_tokens) / len(tag_tokens)
            best = max(best, min(0.90, token_coverage * 0.90))
        tag_characters = {
            character
            for character in compact_tag
            if "\u4e00" <= character <= "\u9fff"
        }
        if tag_characters and query_characters:
            character_coverage = len(query_characters & tag_characters) / len(tag_characters)
            specificity = min(1.0, len(tag_characters) / len(query_characters) * 2)
            best = max(
                best,
                min(0.90, character_coverage * (0.50 + 0.40 * specificity)),
            )
    return best


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
    candidate_limit: int,
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
        rows = session.execute(
            select(EmbeddingRow.entity_id, distance)
            .where(*filters)
            .order_by(distance)
            .limit(candidate_limit)
        ).all()
        return {
            entity_id: max(0.0, min(1.0, 1.0 - float(value)))
            for entity_id, value in rows
        }
    rows = session.scalars(select(EmbeddingRow).where(*filters)).all()
    scored = sorted(
        (
            (
                row.entity_id,
                max(
                    0.0,
                    min(
                        1.0,
                        cosine_similarity(query_vector, _as_float_vector(row.embedding)),
                    ),
                ),
            )
            for row in rows
        ),
        key=lambda item: item[1],
        reverse=True,
    )[:candidate_limit]
    return dict(scored)


def _tag_texts(
    session: Session, *, tenant_id: UUID, product_ids: list[UUID]
) -> dict[UUID, list[str]]:
    if not product_ids:
        return {}
    rows = session.execute(
        select(SkuRow.product_id, PublicCatalogOfferRow.tags)
        .join(
            PublicCatalogOfferRow,
            (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
            & (PublicCatalogOfferRow.sku_id == SkuRow.id),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.product_id.in_(product_ids),
            SkuRow.deleted_at.is_(None),
            PublicCatalogOfferRow.deleted_at.is_(None),
        )
    ).all()
    result: dict[UUID, list[str]] = defaultdict(list)
    for product_id, raw_tags in rows:
        for raw_tag in raw_tags or []:
            tag = str(raw_tag).strip()
            if tag and tag not in result[product_id]:
                result[product_id].append(tag)
    return dict(result)


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
    product_ids: Collection[UUID] | None = None,
    embedder: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    embedder = embedder or resolved_text_embedding_provider(session)
    normalized_query = normalize_text(query)
    if not normalized_query:
        raise ValueError("search query must contain searchable characters")
    query_tokens = _retrieval_tokens(query, query=True)
    document_statement = (
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
    )
    if product_ids is not None:
        allowed_product_ids = list(dict.fromkeys(product_ids))
        if not allowed_product_ids:
            return {
                "query": query,
                "ranking_version": RANKING_VERSION,
                "model": _model_payload(embedder),
                "degraded_channels": ["semantic"],
                "results": [],
            }
        document_statement = document_statement.where(
            ProductRow.id.in_(allowed_product_ids)
        )
    document_rows = session.execute(document_statement).all()
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
    searchable_text_by_document = {
        document.id: "\n".join(
            chunk.content for chunk in chunks_by_document.get(document.id, [])
        )
        for document, _product in document_rows
    }
    searchable_tokens_by_document = {
        document_id: _retrieval_tokens(content)
        for document_id, content in searchable_text_by_document.items()
    }
    document_frequency: Counter[str] = Counter(
        token
        for tokens in searchable_tokens_by_document.values()
        for token in tokens
    )
    query_vector = embedder.embed([query])[0]
    semantic_by_chunk = _semantic_scores(
        session,
        tenant_id=tenant_id,
        chunk_ids=[chunk.id for chunk in chunks],
        query_vector=query_vector,
        embedder=embedder,
        candidate_limit=min(len(chunks), max(96, limit * 12)),
    )
    product_ids = [product.id for _, product in document_rows]
    attribute_text = _attribute_texts(session, tenant_id=tenant_id, product_ids=product_ids)
    tag_text = _tag_texts(session, tenant_id=tenant_id, product_ids=product_ids)
    supplier_scores = _supplier_scores(session, tenant_id=tenant_id, product_ids=product_ids)
    degraded_channels: list[str] = []
    if not semantic_by_chunk:
        degraded_channels.append("semantic")

    ranked: list[tuple[bool, float, dict[str, Any]]] = []
    for document, product in document_rows:
        product_chunks = chunks_by_document.get(document.id, [])
        exact_code = bool(product.product_code) and normalized_query == normalize_text(product.product_code or "")
        keyword = 1.0 if exact_code else _weighted_query_overlap(
            query_tokens,
            searchable_tokens_by_document.get(document.id, set()),
            document_frequency=document_frequency,
            document_count=len(document_rows),
        )
        attribute = _score_overlap(query_tokens, attribute_text.get(product.id, ""))
        tag = _score_tag_relevance(query, query_tokens, tag_text.get(product.id, []))
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
            + WEIGHTS["tag"] * tag
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
                "tag": round(tag, 6),
                "supplier": round(supplier, 6),
            },
            "supplier_signal_status": supplier_status,
            "evidence": evidence,
            "ranking_version": RANKING_VERSION,
            "degraded_channels": list(degraded_channels),
        }
        ranked.append((exact_code, final_score, result))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]["product_code"] or ""), reverse=True)
    if ranked:
        score_floor = max(MINIMUM_RESULT_SCORE, ranked[0][1] * RELATIVE_RESULT_FLOOR)
        ranked = [
            item
            for item in ranked
            if item[0] or item[1] >= score_floor
        ]
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
