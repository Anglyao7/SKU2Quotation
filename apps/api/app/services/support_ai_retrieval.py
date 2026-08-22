from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..repositories import public_catalog_repository
from ..support_ai_models import (
    SupportAIKnowledgeChunkRow,
    SupportAIKnowledgeBaseRow,
    SupportAIKnowledgeSourceRow,
    SupportAISettingsRow,
)
from .embedding import EmbeddingProvider, EmbeddingProviderError, cosine_similarity
from .embedding_configuration import resolved_text_embedding_provider
from .hybrid_search import hybrid_product_search
from .reranking import RerankProviderError, resolved_reranker
from .support_ai_language import preserved_identifiers
from ..model_mixins import utcnow


logger = logging.getLogger(__name__)
CUSTOMER_PRODUCT_FIELD_POLICY_VERSION = 3
SEARCH_SEGMENT_PATTERN = re.compile(
    r"[a-z0-9]+|[\u4e00-\u9fff]+",
    re.IGNORECASE,
)
SQLITE_GLOBAL_VECTOR_SCAN_THRESHOLD = 512
SQLITE_MAX_PRODUCT_CANDIDATES = 96
SUPPORT_RERANK_TIMEOUT_BUDGET_MS = 800
SUPPORT_RERANK_MAX_DOCUMENTS = 30
RETRIEVAL_QUERY_NOISE_PHRASES = (
    "我想了解一下", "你们这里", "你們這裡", "有没有", "有沒有", "适合", "適合",
    "可以推荐", "可以推薦", "推荐", "推薦", "帮我找", "幫我找", "帮我", "幫我",
    "请问", "請問", "我想找", "我想要", "你们", "你們", "这里", "這裡",
    "产品", "產品", "商品", "一下", "的吗", "的嗎", "的", "吗", "嗎",
)
RETRIEVAL_QUERY_STOP_WORDS = {
    "a", "an", "any", "are", "can", "could", "do", "for", "have", "here",
    "i", "item", "items", "looking", "me", "please", "product", "products",
    "recommend", "recommendation", "show", "something", "suitable", "the", "to",
    "want", "what", "which", "with", "you", "your",
}
CUSTOMER_UNSAFE_OPTION_LABEL_PATTERN = re.compile(
    r"(?:^_|supplier|vendor|factory|manufacturer|采购|採購|进货|進貨|成本|利润|利潤|"
    r"供应商|供應商|厂家|廠家|工厂|工廠|内部|內部|备注|備註|note|remark|"
    r"评分|評分|rating|score|联系人|聯繫人|联系方式|聯繫方式|phone|email|"
    r"source)",
    re.IGNORECASE,
)
CUSTOMER_UNSAFE_OPTION_VALUE_PATTERN = re.compile(
    r"(?:supplier\s*[:：]|vendor\s*[:：]|供应商\s*[:：]|供應商\s*[:：]|"
    r"采购价\s*[:：]|採購價\s*[:：]|成本价\s*[:：]|成本價\s*[:：]|"
    r"internal\s*[:：])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    source_type: str
    source_entity_id: str
    source_title: str
    source_version: int
    classification: str
    locator: dict[str, Any]
    excerpt: str
    content_hash: str
    score: float
    knowledge_source_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    evidence: list[RetrievalEvidence]
    diagnostics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QueryEmbeddingState:
    embedder: EmbeddingProvider | None
    vector: list[float] | None
    degraded_reason: str | None
    duration_ms: int = 0


def _lexical_tokens(value: str) -> set[str]:
    result: set[str] = set()
    for segment in SEARCH_SEGMENT_PATTERN.findall(value.casefold()):
        if not segment:
            continue
        if "\u4e00" <= segment[0] <= "\u9fff":
            if len(segment) == 1:
                result.add(segment)
            for width in (2, 3):
                result.update(
                    segment[index : index + width]
                    for index in range(max(0, len(segment) - width + 1))
                )
        else:
            result.add(segment)
    return result


def _lexical_score(query: str, content: str) -> float:
    query_tokens = _lexical_tokens(query)
    if not query_tokens:
        return 0.0
    content_tokens = _lexical_tokens(content)
    matched = query_tokens & content_tokens
    score = len(matched) / len(query_tokens)
    compact_query = " ".join(SEARCH_SEGMENT_PATTERN.findall(query.casefold()))
    compact_content = " ".join(SEARCH_SEGMENT_PATTERN.findall(content.casefold()))
    if compact_query and compact_query in compact_content:
        score = max(score, 0.95)
    identifiers = preserved_identifiers(query)
    if identifiers and any(
        identifier.casefold() in content.casefold()
        for identifier in identifiers
    ):
        score = max(score, 0.92)
    return max(0.0, min(1.0, score))


def _bounded_retrieval_terms(query: str) -> list[str]:
    """Extract substantive terms for the SQLite candidate adapter."""

    normalized = unicodedata.normalize("NFKC", query).casefold()
    for phrase in sorted(RETRIEVAL_QUERY_NOISE_PHRASES, key=len, reverse=True):
        normalized = normalized.replace(phrase.casefold(), " ")
    terms = {
        term
        for term in _lexical_tokens(normalized)
        if len(term) >= 2 and term not in RETRIEVAL_QUERY_STOP_WORDS
    }
    terms.update(identifier.casefold() for identifier in preserved_identifiers(query))
    return sorted(terms, key=lambda value: (-len(value), value))[:16]


def _sqlite_public_product_candidates(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    limit: int,
) -> tuple[list[UUID], dict[str, Any]]:
    """Bound SQLite vector work to lexically plausible public products.

    SQLite stores vectors as JSON and has no ANN operator. Scanning a large
    catalog would parse every vector on every customer turn, so we first select
    a generous public lexical pool and still run the existing hybrid scorer
    (including embeddings) inside that pool.
    """

    started = time.perf_counter()
    terms = _bounded_retrieval_terms(query)
    if not terms:
        return [], {
            "terms": [],
            "matched_rows": 0,
            "matched_products": 0,
            "duration_ms": 0,
        }
    product_limit = max(64, min(SQLITE_MAX_PRODUCT_CANDIDATES, limit * 6))
    rows = public_catalog_repository.list_public_catalog_lexical_candidates(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
        query=query,
        terms=terms,
        category=None,
        limit=product_limit * 3,
    )
    grouped: dict[UUID, list[object]] = defaultdict(list)
    for row in rows:
        grouped[row[2].id].append(row)
    scoring_query = " ".join(terms)
    ranked_ids = [
        product_id
        for _score, product_id in sorted(
            (
                (
                    _lexical_score(
                        scoring_query,
                        _public_product_excerpt(product_rows),
                    ),
                    product_id,
                )
                for product_id, product_rows in grouped.items()
            ),
            key=lambda item: (-item[0], str(item[1])),
        )[:product_limit]
    ]
    return ranked_ids, {
        "terms": terms,
        "matched_rows": len(rows),
        "matched_products": len(grouped),
        "duration_ms": max(0, round((time.perf_counter() - started) * 1000)),
    }


def _float_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return [float(item) for item in value]


def _combined_score(
    *,
    query: str,
    content: str,
    query_vector: list[float] | None,
    content_vector: list[float] | None,
) -> float:
    lexical = _lexical_score(query, content)
    semantic = 0.0
    if query_vector is not None and content_vector is not None:
        if len(query_vector) == len(content_vector):
            semantic = max(
                0.0,
                min(1.0, cosine_similarity(query_vector, content_vector)),
            )
    if content_vector is None or query_vector is None:
        return min(1.0, lexical * 0.88)
    return min(1.0, semantic * 0.72 + lexical * 0.28)


def _support_query_embedding_timeout_seconds() -> float:
    raw = os.getenv("SUPPORT_AI_QUERY_EMBEDDING_TIMEOUT_SECONDS", "1.5").strip()
    try:
        return max(0.2, min(5.0, float(raw)))
    except ValueError:
        return 1.5


def _query_embedding(session: Session, query: str) -> QueryEmbeddingState:
    started = time.perf_counter()
    try:
        embedder = resolved_text_embedding_provider(
            session,
            timeout_seconds=_support_query_embedding_timeout_seconds(),
            max_retry_count=0,
        )
    except (EmbeddingProviderError, ValueError):
        logger.warning("support retrieval embedding configuration is unavailable")
        return QueryEmbeddingState(
            embedder=None,
            vector=None,
            degraded_reason="EMBEDDING_CONFIGURATION_UNAVAILABLE",
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )
    try:
        vector = embedder.embed([query])[0]
    except EmbeddingProviderError:
        logger.warning("support retrieval query embedding failed")
        return QueryEmbeddingState(
            embedder=embedder,
            vector=None,
            degraded_reason="QUERY_EMBEDDING_FAILED",
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        )
    return QueryEmbeddingState(
        embedder=embedder,
        vector=vector,
        degraded_reason=None,
        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
    )


def _customer_visible_product_code(product: object, first_sku: object) -> str:
    product_model = str(
        (getattr(first_sku, "option_values", None) or {}).get("商品型号") or ""
    ).strip()
    stored_product_code = str(getattr(product, "product_code", "") or "").strip()
    if product_model:
        return product_model
    if stored_product_code.startswith(("TPL-", "TPLX-")):
        return str(getattr(first_sku, "sku_code", "") or "").strip()
    return stored_product_code


def _public_product_excerpt(rows: list[object]) -> str:
    _first_offer, first_sku, product, category = rows[0]
    pieces = [f"Product: {product.name}"]
    public_product_code = _customer_visible_product_code(product, first_sku)
    if public_product_code:
        pieces.append(f"Product code: {public_product_code}")
    if product.description:
        pieces.append(f"Description: {product.description}")
    category_value = None
    if category is not None:
        category_value = category.path or category.name
    if category_value:
        pieces.append(f"Category: {category_value}")
    tags = list(
        dict.fromkeys(
            str(tag).strip()
            for offer, _sku, _product, _category in rows
            for tag in (offer.tags or [])
            if str(tag).strip()
        )
    )
    if tags:
        pieces.append("Tags: " + ", ".join(tags))
    for offer, sku, _product, _category in rows[:3]:
        details = [f"SKU: {sku.sku_code}"]
        if sku.name:
            details.append(f"name={sku.name}")
        customer_safe_options = _customer_safe_option_values(sku.option_values)
        if customer_safe_options:
            details.append(
                "options="
                + json.dumps(
                    customer_safe_options,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        if sku.default_moq is not None:
            details.append(
                f"MOQ={sku.default_moq} {sku.moq_unit or ''}".strip()
            )
        details.append(f"public_price={offer.unit_price} {offer.currency}")
        pieces.append("; ".join(details))
    return "\n".join(pieces)[:2200]


def _customer_safe_option_values(values: object) -> dict[str, str]:
    """Project only scalar, customer-safe SKU options into model evidence."""

    if not isinstance(values, dict):
        return {}
    projected: dict[str, str] = {}
    for raw_label, raw_value in values.items():
        label = " ".join(str(raw_label).split())[:120]
        if not label or CUSTOMER_UNSAFE_OPTION_LABEL_PATTERN.search(label):
            continue
        if isinstance(raw_value, (dict, list, tuple, set)):
            continue
        value = " ".join(str(raw_value).split())[:500]
        if not value or CUSTOMER_UNSAFE_OPTION_VALUE_PATTERN.search(value):
            continue
        projected[label] = value
    return projected


def _lexical_public_product_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    public_product_ids: list[UUID],
    limit: int,
) -> list[RetrievalEvidence]:
    rows = public_catalog_repository.list_public_catalog_rows_for_products(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
        product_ids=public_product_ids,
    )
    grouped: dict[UUID, list[object]] = defaultdict(list)
    for row in rows:
        grouped[row[2].id].append(row)
    ranked: list[RetrievalEvidence] = []
    for product_id, product_rows in grouped.items():
        excerpt = _public_product_excerpt(product_rows)
        score = _combined_score(
            query=query,
            content=excerpt,
            query_vector=None,
            content_vector=None,
        )
        if score <= 0:
            continue
        product = product_rows[0][2]
        ranked.append(
            RetrievalEvidence(
                source_type="SKU",
                source_entity_id=str(product_id),
                source_title=product.name,
                source_version=int(product.current_version),
                classification="PUBLIC",
                locator={
                    "type": "public_product",
                    "product_id": str(product_id),
                    "sku_ids": [str(row[1].id) for row in product_rows[:3]],
                    "field_policy_version": (
                        CUSTOMER_PRODUCT_FIELD_POLICY_VERSION
                    ),
                },
                excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                score=score,
            )
        )
    return sorted(ranked, key=lambda row: row.score, reverse=True)[:limit]


def _product_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    embedding: QueryEmbeddingState,
    limit: int,
) -> tuple[list[RetrievalEvidence], dict[str, Any]]:
    started = time.perf_counter()
    candidate_limit = max(12, min(48, limit * 6))
    dialect = session.get_bind().dialect.name
    candidate_adapter = "GLOBAL_VECTOR_INDEX"
    candidate_trace: dict[str, Any] | None = None
    if dialect == "sqlite":
        public_product_count = (
            public_catalog_repository.count_public_catalog_products(
                session,
                tenant_id=tenant_id,
                now=utcnow(),
                query="",
                category=None,
                tags=set(),
            )
        )
        if public_product_count <= SQLITE_GLOBAL_VECTOR_SCAN_THRESHOLD:
            public_product_ids = (
                public_catalog_repository.list_public_catalog_product_ids(
                    session,
                    tenant_id=tenant_id,
                    now=utcnow(),
                )
            )
            candidate_adapter = "FULL_SMALL_CATALOG"
        else:
            public_product_ids, candidate_trace = (
                _sqlite_public_product_candidates(
                    session,
                    tenant_id=tenant_id,
                    query=query,
                    limit=candidate_limit,
                )
            )
            candidate_adapter = "SQLITE_BOUNDED_CANDIDATES"
    else:
        public_product_ids = (
            public_catalog_repository.list_public_catalog_product_ids(
                session,
                tenant_id=tenant_id,
                now=utcnow(),
            )
        )
        public_product_count = len(public_product_ids)
    diagnostics: dict[str, Any] = {
        "public_eligible_products": public_product_count,
        "candidate_pool_products": len(public_product_ids),
        "candidate_adapter": candidate_adapter,
        "candidate_trace": candidate_trace,
        "engine": "HYBRID_PRODUCT_SEARCH",
        "hybrid_results": 0,
        "degraded_channels": [],
    }
    if not public_product_ids:
        diagnostics["duration_ms"] = max(
            0, round((time.perf_counter() - started) * 1000)
        )
        return [], diagnostics
    if embedding.embedder is None:
        diagnostics["engine"] = "LEXICAL_PUBLIC_FALLBACK"
        diagnostics["degraded_channels"] = ["semantic"]
        fallback = _lexical_public_product_evidence(
            session,
            tenant_id=tenant_id,
            query=query,
            public_product_ids=public_product_ids,
            limit=candidate_limit,
        )
        diagnostics["hybrid_results"] = len(fallback)
        diagnostics["duration_ms"] = max(
            0, round((time.perf_counter() - started) * 1000)
        )
        return fallback, diagnostics

    result = hybrid_product_search(
        session,
        tenant_id=tenant_id,
        query=query,
        limit=candidate_limit,
        product_ids=public_product_ids,
        embedder=embedding.embedder,
        precomputed_query_vector=embedding.vector,
        semantic_search_enabled=embedding.vector is not None,
        supplier_scoring_enabled=False,
    )
    ranked_rows = list(result.get("results") or [])
    diagnostics["hybrid_results"] = len(ranked_rows)
    diagnostics["degraded_channels"] = list(
        result.get("degraded_channels") or []
    )
    if candidate_adapter == "SQLITE_BOUNDED_CANDIDATES":
        diagnostics["degraded_channels"] = list(
            dict.fromkeys(
                [
                    *diagnostics["degraded_channels"],
                    "global_semantic_recall",
                ]
            )
        )
    ranked_product_ids = [UUID(str(row["product_id"])) for row in ranked_rows]
    public_rows = public_catalog_repository.list_public_catalog_rows_for_products(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
        product_ids=ranked_product_ids,
    )
    rows_by_product: dict[UUID, list[object]] = defaultdict(list)
    for row in public_rows:
        rows_by_product[row[2].id].append(row)
    evidence: list[RetrievalEvidence] = []
    for ranked in ranked_rows:
        product_id = UUID(str(ranked["product_id"]))
        product_rows = rows_by_product.get(product_id, [])
        if not product_rows:
            continue
        product = product_rows[0][2]
        excerpt = _public_product_excerpt(product_rows)
        score_breakdown = ranked.get("score_breakdown") or {}
        support_relevance_score = max(
            float(ranked.get("score") or 0),
            float(score_breakdown.get("semantic") or 0),
        )
        evidence.append(
            RetrievalEvidence(
                source_type="SKU",
                source_entity_id=str(product_id),
                source_title=product.name,
                source_version=int(ranked.get("source_version") or product.current_version),
                classification="PUBLIC",
                locator={
                    "type": "public_product",
                    "product_id": str(product_id),
                    "sku_ids": [str(row[1].id) for row in product_rows[:3]],
                    "ranking_version": result.get("ranking_version"),
                    "field_policy_version": (
                        CUSTOMER_PRODUCT_FIELD_POLICY_VERSION
                    ),
                },
                excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                score=max(0.0, min(1.0, support_relevance_score)),
            )
        )
    diagnostics["duration_ms"] = max(
        0, round((time.perf_counter() - started) * 1000)
    )
    return evidence, diagnostics


def _generic_recommendation_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    limit: int,
) -> tuple[list[RetrievalEvidence], dict[str, Any]]:
    """Return a bounded, category-diverse public pool without query embedding."""

    started = time.perf_counter()
    candidate_limit = max(8, min(24, limit * 4))
    product_ids = public_catalog_repository.list_public_product_ids_page(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
        query="",
        category=None,
        tags=set(),
        page=1,
        page_size=candidate_limit,
        hot=True,
    )
    rows = public_catalog_repository.list_public_catalog_rows_for_products(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
        product_ids=product_ids,
    )
    grouped: dict[UUID, list[object]] = defaultdict(list)
    for row in rows:
        grouped[row[2].id].append(row)

    ordered_groups = [
        grouped[product_id]
        for product_id in product_ids
        if product_id in grouped
    ]
    diverse: list[list[object]] = []
    remaining: list[list[object]] = []
    seen_categories: set[str] = set()
    for product_rows in ordered_groups:
        category = product_rows[0][3]
        category_key = str(
            getattr(category, "path", None)
            or getattr(category, "name", None)
            or "uncategorized"
        ).casefold()
        if category_key not in seen_categories:
            seen_categories.add(category_key)
            diverse.append(product_rows)
        else:
            remaining.append(product_rows)
    selected_groups = (diverse + remaining)[:candidate_limit]

    evidence: list[RetrievalEvidence] = []
    for index, product_rows in enumerate(selected_groups):
        product = product_rows[0][2]
        excerpt = _public_product_excerpt(product_rows)
        evidence.append(
            RetrievalEvidence(
                source_type="SKU",
                source_entity_id=str(product.id),
                source_title=product.name,
                source_version=int(product.current_version),
                classification="PUBLIC",
                locator={
                    "type": "public_product",
                    "product_id": str(product.id),
                    "sku_ids": [str(row[1].id) for row in product_rows[:3]],
                    "field_policy_version": CUSTOMER_PRODUCT_FIELD_POLICY_VERSION,
                    "recommendation_pool": "HOT_AND_CURATED",
                },
                excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                score=max(0.25, 0.65 - index * 0.008),
            )
        )
    return evidence, {
        "public_eligible_products": len(product_ids),
        "engine": "CURATED_RECOMMENDATION_POOL",
        "hybrid_results": len(evidence),
        "degraded_channels": [],
        "duration_ms": max(0, round((time.perf_counter() - started) * 1000)),
    }


def _rerank_candidates(
    session: Session,
    *,
    query: str,
    candidates: list[RetrievalEvidence],
    skip_reason: str | None = None,
) -> tuple[list[RetrievalEvidence], dict[str, Any]]:
    trace: dict[str, Any] = {
        "configured": False,
        "applied": False,
        "candidate_count": len(candidates),
        "duration_ms": 0,
        "degraded_reason": skip_reason,
    }
    if skip_reason or len(candidates) < 2:
        return candidates, trace
    try:
        provider = resolved_reranker(
            session,
            timeout_cap_ms=SUPPORT_RERANK_TIMEOUT_BUDGET_MS,
            max_documents_cap=SUPPORT_RERANK_MAX_DOCUMENTS,
        )
    except (RerankProviderError, ValueError):
        trace["degraded_reason"] = "RERANK_CONFIGURATION_UNAVAILABLE"
        return candidates, trace
    if provider is None:
        trace["degraded_reason"] = "RERANK_DISABLED"
        return candidates, trace
    trace["configured"] = True
    bounded = candidates[: provider.max_documents]
    started = time.perf_counter()
    try:
        results = provider.rerank(
            query=query,
            documents=[row.excerpt[:2200] for row in bounded],
            top_n=len(bounded),
        )
    except RerankProviderError as exc:
        trace["duration_ms"] = max(
            0, round((time.perf_counter() - started) * 1000)
        )
        trace["degraded_reason"] = (
            "RERANK_TIMEOUT"
            if "timed out" in str(exc).casefold()
            else "RERANK_FAILED"
        )
        return candidates, trace

    rerank_position = {result.index: index for index, result in enumerate(results)}
    rerank_score = {
        result.index: round(result.relevance_score, 6) for result in results
    }
    base_position = {index: index for index in range(len(bounded))}
    ordered_indices = sorted(
        range(len(bounded)),
        key=lambda index: -(
            0.65 / (60 + rerank_position.get(index, len(bounded)))
            + 0.35 / (60 + base_position[index])
        ),
    )
    reordered = [bounded[index] for index in ordered_indices]
    reordered.extend(candidates[len(bounded) :])
    trace.update(
        applied=True,
        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
        degraded_reason=None,
        reranked_count=len(bounded),
        returned_count=len(results),
        relevance_scores=[
            rerank_score[index]
            for index in ordered_indices
            if index in rerank_score
        ],
    )
    return reordered, trace


def _file_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    agent_id: UUID | None,
    query: str,
    embedding: QueryEmbeddingState,
) -> tuple[list[RetrievalEvidence], int]:
    if agent_id is not None:
        scope_filter = (
            (
                SupportAIKnowledgeBaseRow.id.is_not(None)
                & (SupportAIKnowledgeBaseRow.agent_id == agent_id)
                & (SupportAIKnowledgeBaseRow.status == "ACTIVE")
            )
            | (
                SupportAIKnowledgeSourceRow.knowledge_base_id.is_(None)
                & (SupportAIKnowledgeSourceRow.agent_id == agent_id)
            )
        )
    else:
        scope_filter = (
            SupportAIKnowledgeBaseRow.id.is_(None)
            & SupportAIKnowledgeSourceRow.knowledge_base_id.is_(None)
            & SupportAIKnowledgeSourceRow.agent_id.is_(None)
        )
    rows = session.execute(
        select(SupportAIKnowledgeChunkRow, SupportAIKnowledgeSourceRow)
        .join(
            SupportAIKnowledgeSourceRow,
            (
                SupportAIKnowledgeSourceRow.tenant_id
                == SupportAIKnowledgeChunkRow.tenant_id
            )
            & (
                SupportAIKnowledgeSourceRow.id
                == SupportAIKnowledgeChunkRow.source_id
            ),
        )
        .outerjoin(
            SupportAIKnowledgeBaseRow,
            (
                SupportAIKnowledgeBaseRow.tenant_id
                == SupportAIKnowledgeSourceRow.tenant_id
            )
            & (
                SupportAIKnowledgeBaseRow.id
                == SupportAIKnowledgeSourceRow.knowledge_base_id
            ),
        )
        .where(
            SupportAIKnowledgeChunkRow.tenant_id == tenant_id,
            SupportAIKnowledgeChunkRow.status == "ACTIVE",
            # Rows written before first-class knowledge bases were introduced
            # remain readable while migrations/backfills complete.
            scope_filter,
            (
                (SupportAIKnowledgeSourceRow.status == "APPROVED")
                | (
                    (SupportAIKnowledgeSourceRow.status == "READY")
                    & ~SupportAIKnowledgeSourceRow.original_filename.ilike("%.json")
                )
            ),
            SupportAIKnowledgeSourceRow.classification.in_(
                ["PUBLIC", "CUSTOMER_APPROVED"]
            ),
        )
        .order_by(
            SupportAIKnowledgeSourceRow.updated_at.desc(),
            SupportAIKnowledgeChunkRow.chunk_index,
        )
        .limit(10000)
    ).all()
    evidence: list[RetrievalEvidence] = []
    for chunk, source in rows:
        content_vector: list[float] | None = None
        if (
            embedding.embedder is not None
            and chunk.embedding is not None
            and chunk.embedding_provider == embedding.embedder.identity.provider
            and chunk.embedding_model == embedding.embedder.identity.model_name
            and chunk.embedding_version == embedding.embedder.identity.model_version
            and chunk.embedding_dimensions == embedding.embedder.identity.dimensions
        ):
            content_vector = _float_vector(chunk.embedding)
        score = _combined_score(
            query=query,
            content=chunk.content,
            query_vector=embedding.vector,
            content_vector=content_vector,
        )
        locator = dict(chunk.locator or {})
        locator.setdefault("section", chunk.section_path)
        evidence.append(
            RetrievalEvidence(
                source_type="FILE",
                source_entity_id=str(source.id),
                source_title=source.title,
                source_version=int(source.version),
                classification=source.classification,
                locator=locator,
                excerpt=chunk.content[:2200],
                content_hash=chunk.content_hash,
                score=score,
                knowledge_source_id=source.id,
            )
        )
    return evidence, len(rows)


def retrieve_customer_evidence_with_trace(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    settings: SupportAISettingsRow,
    interaction_goal: str = "QUESTION_ANSWERING",
    generic_recommendation: bool = False,
) -> RetrievalBundle:
    retrieval_started = time.perf_counter()
    embedding = (
        QueryEmbeddingState(
            embedder=None,
            vector=None,
            degraded_reason="SKIPPED_GENERIC_RECOMMENDATION",
            duration_ms=0,
        )
        if generic_recommendation
        else _query_embedding(session, query)
    )
    candidates: list[RetrievalEvidence] = []
    product_trace: dict[str, Any] = {
        "public_eligible_products": 0,
        "engine": "DISABLED",
        "hybrid_results": 0,
        "degraded_channels": [],
    }
    if settings.sku_knowledge_enabled:
        if generic_recommendation:
            product_candidates, product_trace = _generic_recommendation_evidence(
                session,
                tenant_id=tenant_id,
                limit=settings.max_sources,
            )
        else:
            product_candidates, product_trace = _product_evidence(
                session,
                tenant_id=tenant_id,
                query=query,
                embedding=embedding,
                limit=settings.max_sources,
            )
        candidates.extend(product_candidates)
    file_candidate_count = 0
    file_duration_ms = 0
    if settings.file_knowledge_enabled and not generic_recommendation:
        file_started = time.perf_counter()
        file_candidates, file_candidate_count = _file_evidence(
            session,
            tenant_id=tenant_id,
            agent_id=settings.agent_id,
            query=query,
            embedding=embedding,
        )
        candidates.extend(file_candidates)
        file_duration_ms = max(
            0, round((time.perf_counter() - file_started) * 1000)
        )

    minimum = float(settings.min_retrieval_score)
    ranked = sorted(candidates, key=lambda row: row.score, reverse=True)
    eligible: list[RetrievalEvidence] = []
    seen: set[tuple[str, str]] = set()
    for candidate in ranked:
        if candidate.score < minimum:
            continue
        key = (candidate.source_type, candidate.content_hash)
        if key in seen:
            continue
        seen.add(key)
        eligible.append(candidate)
    rerank_skip_reason: str | None = None
    if generic_recommendation:
        rerank_skip_reason = "GENERIC_RECOMMENDATION_POOL"
    elif preserved_identifiers(query):
        # Exact SKU/model lookups already have a deterministic lexical boost.
        # A semantic reranker must not move an exact identifier behind a fuzzy hit.
        rerank_skip_reason = "EXACT_IDENTIFIER_QUERY"
    eligible, rerank_trace = _rerank_candidates(
        session,
        query=query,
        candidates=eligible,
        skip_reason=rerank_skip_reason,
    )
    source_limit = (
        min(2, settings.max_sources)
        if generic_recommendation
        else settings.max_sources
    )
    unique = eligible[:source_limit]

    diagnostics = {
        "query_embedding": (
            "AVAILABLE" if embedding.vector is not None else "DEGRADED"
        ),
        "query_embedding_degraded_reason": embedding.degraded_reason,
        "query_embedding_duration_ms": embedding.duration_ms,
        "sku_knowledge_enabled": bool(settings.sku_knowledge_enabled),
        "file_knowledge_enabled": bool(settings.file_knowledge_enabled),
        "product": product_trace,
        "file_candidate_chunks": file_candidate_count,
        "file_retrieval_duration_ms": file_duration_ms,
        "candidate_count": len(candidates),
        "accepted_count": len(unique),
        "minimum_score": minimum,
        "top_candidate_score": round(ranked[0].score, 6) if ranked else None,
        "accepted_scores": [round(row.score, 6) for row in unique],
        "customer_product_field_policy_version": (
            CUSTOMER_PRODUCT_FIELD_POLICY_VERSION
        ),
        "interaction_goal": interaction_goal,
        "retrieval_mode": (
            "GENERIC_RECOMMENDATION_POOL"
            if generic_recommendation
            else "HYBRID_RAG"
        ),
        "rerank": rerank_trace,
        "total_duration_ms": max(
            0, round((time.perf_counter() - retrieval_started) * 1000)
        ),
    }
    return RetrievalBundle(evidence=unique, diagnostics=diagnostics)


def retrieve_customer_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    settings: SupportAISettingsRow,
) -> list[RetrievalEvidence]:
    return retrieve_customer_evidence_with_trace(
        session,
        tenant_id=tenant_id,
        query=query,
        settings=settings,
    ).evidence
