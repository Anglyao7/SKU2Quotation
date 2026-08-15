from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import logging
import re
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
from .support_ai_language import preserved_identifiers
from ..model_mixins import utcnow


logger = logging.getLogger(__name__)
CUSTOMER_PRODUCT_FIELD_POLICY_VERSION = 3
SEARCH_SEGMENT_PATTERN = re.compile(
    r"[a-z0-9]+|[\u4e00-\u9fff]+",
    re.IGNORECASE,
)
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


def _query_embedding(session: Session, query: str) -> QueryEmbeddingState:
    try:
        embedder = resolved_text_embedding_provider(session)
    except (EmbeddingProviderError, ValueError):
        logger.warning("support retrieval embedding configuration is unavailable")
        return QueryEmbeddingState(
            embedder=None,
            vector=None,
            degraded_reason="EMBEDDING_CONFIGURATION_UNAVAILABLE",
        )
    try:
        vector = embedder.embed([query])[0]
    except EmbeddingProviderError:
        logger.warning("support retrieval query embedding failed")
        return QueryEmbeddingState(
            embedder=embedder,
            vector=None,
            degraded_reason="QUERY_EMBEDDING_FAILED",
        )
    return QueryEmbeddingState(
        embedder=embedder,
        vector=vector,
        degraded_reason=None,
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
    public_product_ids = public_catalog_repository.list_public_catalog_product_ids(
        session,
        tenant_id=tenant_id,
        now=utcnow(),
    )
    diagnostics: dict[str, Any] = {
        "public_eligible_products": len(public_product_ids),
        "engine": "HYBRID_PRODUCT_SEARCH",
        "hybrid_results": 0,
        "degraded_channels": [],
    }
    if not public_product_ids:
        return [], diagnostics
    candidate_limit = max(12, min(48, limit * 6))
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
    return evidence, diagnostics


def _file_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    agent_id: UUID | None,
    query: str,
    embedding: QueryEmbeddingState,
) -> tuple[list[RetrievalEvidence], int]:
    rows = session.execute(
        select(
            SupportAIKnowledgeChunkRow,
            SupportAIKnowledgeSourceRow,
            SupportAIKnowledgeBaseRow,
        )
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
        .join(
            SupportAIKnowledgeBaseRow,
            SupportAIKnowledgeBaseRow.id
            == SupportAIKnowledgeSourceRow.knowledge_base_id,
        )
        .where(
            SupportAIKnowledgeChunkRow.tenant_id == tenant_id,
            SupportAIKnowledgeChunkRow.status == "ACTIVE",
            SupportAIKnowledgeBaseRow.tenant_id == tenant_id,
            SupportAIKnowledgeBaseRow.status == "ACTIVE",
            SupportAIKnowledgeBaseRow.agent_id == agent_id,
            (
                SupportAIKnowledgeSourceRow.status == "APPROVED"
            )
            | (
                (SupportAIKnowledgeSourceRow.status == "READY")
                & ~SupportAIKnowledgeSourceRow.original_filename.ilike("%.json")
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
    for chunk, source, _knowledge_base in rows:
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
) -> RetrievalBundle:
    embedding = _query_embedding(session, query)
    candidates: list[RetrievalEvidence] = []
    product_trace: dict[str, Any] = {
        "public_eligible_products": 0,
        "engine": "DISABLED",
        "hybrid_results": 0,
        "degraded_channels": [],
    }
    if settings.sku_knowledge_enabled:
        product_candidates, product_trace = _product_evidence(
            session,
            tenant_id=tenant_id,
            query=query,
            embedding=embedding,
            limit=settings.max_sources,
        )
        candidates.extend(product_candidates)
    file_candidate_count = 0
    if settings.file_knowledge_enabled:
        file_candidates, file_candidate_count = _file_evidence(
            session,
            tenant_id=tenant_id,
            agent_id=settings.agent_id,
            query=query,
            embedding=embedding,
        )
        candidates.extend(file_candidates)

    minimum = float(settings.min_retrieval_score)
    ranked = sorted(candidates, key=lambda row: row.score, reverse=True)
    unique: list[RetrievalEvidence] = []
    seen: set[tuple[str, str]] = set()
    for candidate in ranked:
        if candidate.score < minimum:
            continue
        key = (candidate.source_type, candidate.content_hash)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= settings.max_sources:
            break

    diagnostics = {
        "query_embedding": (
            "AVAILABLE" if embedding.vector is not None else "DEGRADED"
        ),
        "query_embedding_degraded_reason": embedding.degraded_reason,
        "sku_knowledge_enabled": bool(settings.sku_knowledge_enabled),
        "file_knowledge_enabled": bool(settings.file_knowledge_enabled),
        "product": product_trace,
        "file_candidate_chunks": file_candidate_count,
        "candidate_count": len(candidates),
        "accepted_count": len(unique),
        "minimum_score": minimum,
        "top_candidate_score": round(ranked[0].score, 6) if ranked else None,
        "accepted_scores": [round(row.score, 6) for row in unique],
        "customer_product_field_policy_version": (
            CUSTOMER_PRODUCT_FIELD_POLICY_VERSION
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
