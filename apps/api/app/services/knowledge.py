import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, distinct, func, or_, select, update
from sqlalchemy.orm import Session

from ..db_models import SupplierRow
from ..knowledge_embedding_models import EmbeddingRow, KnowledgeChunkRow, KnowledgeDocumentRow
from ..model_mixins import utcnow
from ..product_center_models import SkuRow
from ..product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductRow,
    SupplierProductRow,
)
from ..public_catalog_models import PublicCatalogOfferRow
from .embedding import (
    EmbeddingProvider,
    precompute_embeddings,
    validate_vectors,
)
from .embedding_configuration import resolved_text_embedding_provider


SCHEMA_VERSION = 3
FIELD_POLICY_VERSION = 3
LOCALE = "und"
FEATURE_MARKERS = ("feature", "use", "application", "cert", "特点", "用途", "认证")
MARKET_MARKERS = ("market", "country", "region", "市场", "国家", "地区")
UNCATEGORIZED_CATEGORY_NAME = "未分类"


class KnowledgeProjectionError(ValueError):
    pass


class KnowledgeIndexExcludedError(ValueError):
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


@dataclass(frozen=True)
class KnowledgeIndexStatus:
    total_products: int
    indexed_products: int
    pending_products: int
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int


@dataclass(frozen=True)
class KnowledgeIndexUpdateResult:
    mode: str
    processed_products: int
    total_products: int
    indexed_products: int
    pending_products: int
    embeddings: int
    model_provider: str
    model_name: str
    model_version: str
    dimensions: int


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
    if category is not None and category.name.strip() == UNCATEGORIZED_CATEGORY_NAME:
        raise KnowledgeIndexExcludedError("未分类商品不会纳入智能索引")
    attributes = session.scalars(
        select(ProductAttributeRow)
        .where(
            ProductAttributeRow.tenant_id == tenant_id,
            ProductAttributeRow.product_id == product.id,
            ProductAttributeRow.review_status == "CONFIRMED",
        )
        .order_by(ProductAttributeRow.attribute_key, ProductAttributeRow.id)
    ).all()
    supplier_rows = session.scalars(
        select(SupplierProductRow)
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
    sku_rows = session.execute(
        select(SkuRow, PublicCatalogOfferRow)
        .outerjoin(
            PublicCatalogOfferRow,
            (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
            & (PublicCatalogOfferRow.sku_id == SkuRow.id)
            & (PublicCatalogOfferRow.deleted_at.is_(None)),
        )
        .where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.product_id == product.id,
            SkuRow.status == "ACTIVE",
            SkuRow.deleted_at.is_(None),
        )
        .order_by(SkuRow.sku_code, SkuRow.id)
    ).all()

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
        "skus": [
            {
                "code": sku.sku_code,
                "name": sku.name,
                "options": _json_value(sku.option_values),
                "barcode": sku.barcode,
                "default_moq": _json_value(sku.default_moq),
                "moq_unit": sku.moq_unit,
                "tags": [
                    str(tag).strip()
                    for tag in (offer.tags if offer is not None else [])
                    if str(tag).strip()
                ],
            }
            for sku, offer in sku_rows
        ],
        "suppliers": [
            {
                "moq": _json_value(supplier_product.moq),
                "moq_unit": supplier_product.moq_unit,
                "lead_time_days": supplier_product.lead_time_days,
            }
            for supplier_product in supplier_rows
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
    skus = payload.get("skus", [])
    suppliers = payload.get("suppliers", [])
    search_tags = list(dict.fromkeys(
        str(tag).strip()
        for sku in skus
        for tag in sku.get("tags", [])
        if str(tag).strip()
    ))

    sku_moq_items: list[str] = []
    represented_moqs: set[str] = set()
    for sku in skus:
        if sku.get("default_moq") is None:
            continue
        moq = f"{sku['default_moq']} {sku.get('moq_unit') or ''}".strip()
        sku_code = str(sku.get("code") or "SKU").strip()
        sku_moq_items.append(f"{sku_code}={moq}")
        represented_moqs.add(moq.casefold())

    moq_options: list[str] = []
    for supplier in suppliers:
        if supplier.get("moq") is None:
            continue
        moq = f"{supplier['moq']} {supplier.get('moq_unit') or ''}".strip()
        normalized_moq = moq.casefold()
        if normalized_moq in represented_moqs:
            continue
        represented_moqs.add(normalized_moq)
        moq_options.append(moq)

    overview_lines = [
        f"Product code: {product.get('code') or ''}",
        f"Product name: {product.get('name') or ''}",
        f"Category: {category.get('name') or ''}",
        f"Description: {product.get('description') or ''}",
        f"Search tags / 商品标签: {_render_value(search_tags)}" if search_tags else "",
        f"SKU MOQ / SKU最低起订量: {'; '.join(sku_moq_items)}" if sku_moq_items else "",
        f"MOQ options / 最低起订量选项: {'; '.join(moq_options)}" if moq_options else "",
    ]
    sections: dict[str, list[str]] = {
        "OVERVIEW": [line for line in overview_lines if line and not line.endswith(": ")],
        "SPECIFICATIONS": [],
        "FEATURES": [],
        "MARKETS": [],
        "SUPPLY": [],
    }
    for sku in skus:
        details = [f"SKU: {sku['code']}"]
        if sku.get("name"):
            details.append(f"name={sku['name']}")
        if sku.get("options"):
            details.append(f"options={_render_value(sku['options'])}")
        if sku.get("barcode"):
            details.append(f"barcode={sku['barcode']}")
        if sku.get("tags"):
            details.append(f"tags={_render_value(sku['tags'])}")
        if sku.get("default_moq") is not None:
            details.append(
                f"moq={sku['default_moq']} {sku.get('moq_unit') or ''}".strip()
            )
        sections["SPECIFICATIONS"].append("; ".join(details))
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
    for supplier in suppliers:
        details = []
        if supplier.get("moq") is not None:
            details.append(f"moq={supplier['moq']} {supplier.get('moq_unit') or ''}".strip())
        if supplier.get("lead_time_days") is not None:
            details.append(f"lead_time_days={supplier['lead_time_days']}")
        if details:
            sections["SUPPLY"].append("; ".join(details))

    chunks: list[dict[str, Any]] = []
    for chunk_type in ("OVERVIEW", "SPECIFICATIONS", "FEATURES", "MARKETS", "SUPPLY"):
        lines = sections[chunk_type]
        if not lines:
            continue
        content = "\n".join(lines)
        metadata: dict[str, Any] = {
            "source": "Product Center",
            "field_policy_version": FIELD_POLICY_VERSION,
        }
        if chunk_type == "OVERVIEW" and search_tags:
            metadata["search_tags"] = search_tags
        chunks.append(
            {
                "chunk_index": len(chunks),
                "chunk_type": chunk_type,
                "section_path": f"product/{chunk_type.casefold()}",
                "content": content,
                "content_hash": _sha256(content),
                "token_count": len(content.split()),
                "metadata": metadata,
            }
        )
    return chunks


def project_product_knowledge(
    session: Session,
    *,
    tenant_id: UUID,
    product_id: UUID,
    embedder: EmbeddingProvider | None = None,
    force_reembed: bool = False,
) -> KnowledgeProjectionResult:
    embedder = embedder or resolved_text_embedding_provider(session)
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
        chunks = session.scalars(
            select(KnowledgeChunkRow).where(
                KnowledgeChunkRow.tenant_id == tenant_id,
                KnowledgeChunkRow.document_id == existing.id,
                KnowledgeChunkRow.status == "ACTIVE",
            )
        ).all()
        existing_embeddings = []
        if chunks:
            existing_embeddings = session.scalars(
                select(EmbeddingRow)
                .where(
                    EmbeddingRow.tenant_id == tenant_id,
                    EmbeddingRow.entity_type == "KNOWLEDGE_CHUNK",
                    EmbeddingRow.entity_id.in_([chunk.id for chunk in chunks]),
                    EmbeddingRow.embedding_type == "KNOWLEDGE_CHUNK",
                    EmbeddingRow.model_provider == embedder.identity.provider,
                    EmbeddingRow.model_name == embedder.identity.model_name,
                    EmbeddingRow.model_version == embedder.identity.model_version,
                    EmbeddingRow.dimensions == embedder.identity.dimensions,
                    EmbeddingRow.status == "ACTIVE",
                )
            ).all()
        embeddings_by_chunk_id = {
            row.entity_id: row for row in existing_embeddings
        }
        target_chunks = (
            list(chunks)
            if force_reembed
            else [
                chunk
                for chunk in chunks
                if chunk.id not in embeddings_by_chunk_id
            ]
        )
        if target_chunks:
            vectors = embedder.embed([chunk.content for chunk in target_chunks])
            validate_vectors(
                vectors,
                expected_count=len(target_chunks),
                dimensions=embedder.identity.dimensions,
            )
            for chunk, vector in zip(target_chunks, vectors, strict=True):
                embedding = embeddings_by_chunk_id.get(chunk.id)
                if embedding is None:
                    embedding = EmbeddingRow(
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
                    session.add(embedding)
                    embeddings_by_chunk_id[chunk.id] = embedding
                else:
                    embedding.embedding = vector
                    embedding.content_hash = chunk.content_hash
                    embedding.entity_version = chunk.record_version
                    embedding.permission_scope = chunk.permission_scope
                    embedding.activated_at = utcnow()
                    embedding.superseded_at = None
                    embedding.status = "ACTIVE"
            session.flush()
        product.search_document_version = product.current_version
        session.flush()
        return KnowledgeProjectionResult(
            document_id=existing.id,
            product_id=product.id,
            source_version=product.current_version,
            chunks=len(chunks),
            embeddings=len(embeddings_by_chunk_id),
            model_provider=embedder.identity.provider,
            model_name=embedder.identity.model_name,
            model_version=embedder.identity.model_version,
            dimensions=embedder.identity.dimensions,
            idempotent=not target_chunks,
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


def project_products_knowledge(
    session: Session,
    *,
    tenant_id: UUID,
    product_ids: list[UUID],
    embedder: EmbeddingProvider | None = None,
    embedding_batch_size: int = 128,
    force_reembed: bool = False,
) -> list[KnowledgeProjectionResult]:
    """Project a bounded group while batching remote embedding requests."""

    if not product_ids:
        return []
    embedder = embedder or resolved_text_embedding_provider(session)
    ordered_product_ids = list(dict.fromkeys(product_ids))
    texts: list[str] = []
    for product_id in ordered_product_ids:
        _product, payload = build_product_payload(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
        )
        texts.extend(
            chunk["content"]
            for chunk in build_product_chunks(payload)
        )
    cached_embedder = precompute_embeddings(
        embedder,
        texts,
        batch_size=embedding_batch_size,
    )
    return [
        project_product_knowledge(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
            embedder=cached_embedder,
            force_reembed=force_reembed,
        )
        for product_id in ordered_product_ids
    ]


def _deactivate_product_knowledge(
    session: Session,
    *,
    tenant_id: UUID,
    product_ids: list[UUID],
) -> None:
    """Retire active documents for products that are no longer index-eligible."""

    product_ids = list(dict.fromkeys(product_ids))
    if not product_ids:
        return
    now = utcnow()
    active_document_ids = session.scalars(
        select(KnowledgeDocumentRow.id).where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.source_entity_type == "PRODUCT",
            KnowledgeDocumentRow.source_entity_id.in_(product_ids),
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
    session.execute(
        update(ProductRow)
        .where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id.in_(product_ids),
        )
        .values(search_document_version=0, updated_at=now)
    )
    session.flush()


def indexed_product_ids(
    session: Session,
    *,
    tenant_id: UUID,
    embedder: EmbeddingProvider | None = None,
) -> set[UUID]:
    embedder = embedder or resolved_text_embedding_provider(session)
    rows = session.scalars(
        select(KnowledgeDocumentRow.source_entity_id)
        .join(
            ProductRow,
            (ProductRow.tenant_id == KnowledgeDocumentRow.tenant_id)
            & (ProductRow.id == KnowledgeDocumentRow.source_entity_id),
        )
        .join(
            KnowledgeChunkRow,
            (KnowledgeChunkRow.tenant_id == KnowledgeDocumentRow.tenant_id)
            & (KnowledgeChunkRow.document_id == KnowledgeDocumentRow.id)
            & (KnowledgeChunkRow.status == "ACTIVE"),
        )
        .outerjoin(
            ProductCategoryRow,
            (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
            & (ProductCategoryRow.id == ProductRow.category_id)
            & (ProductCategoryRow.status == "ACTIVE"),
        )
        .outerjoin(
            EmbeddingRow,
            and_(
                # Keep the complete active-projection identity in this join.
                # Besides preventing another embedding kind from being counted,
                # this lets SQLite/PostgreSQL use the active entity/model index
                # instead of scanning every vector for the configured model.
                EmbeddingRow.tenant_id == KnowledgeChunkRow.tenant_id,
                EmbeddingRow.entity_type == "KNOWLEDGE_CHUNK",
                EmbeddingRow.entity_id == KnowledgeChunkRow.id,
                EmbeddingRow.embedding_type == "KNOWLEDGE_CHUNK",
                EmbeddingRow.model_provider == embedder.identity.provider,
                EmbeddingRow.model_name == embedder.identity.model_name,
                EmbeddingRow.model_version == embedder.identity.model_version,
                EmbeddingRow.dimensions == embedder.identity.dimensions,
                EmbeddingRow.status == "ACTIVE",
                EmbeddingRow.deleted_at.is_(None),
            ),
        )
        .where(
            KnowledgeDocumentRow.tenant_id == tenant_id,
            KnowledgeDocumentRow.source_entity_type == "PRODUCT",
            KnowledgeDocumentRow.schema_version == SCHEMA_VERSION,
            KnowledgeDocumentRow.field_policy_version == FIELD_POLICY_VERSION,
            KnowledgeDocumentRow.locale == LOCALE,
            KnowledgeDocumentRow.status == "ACTIVE",
            ProductRow.status == "ACTIVE",
            or_(
                ProductCategoryRow.id.is_(None),
                func.trim(ProductCategoryRow.name) != UNCATEGORIZED_CATEGORY_NAME,
            ),
            ProductRow.search_document_version == ProductRow.current_version,
            KnowledgeDocumentRow.source_version == ProductRow.current_version,
        )
        .group_by(KnowledgeDocumentRow.source_entity_id)
        .having(
            func.count(distinct(KnowledgeChunkRow.id))
            == func.count(distinct(EmbeddingRow.entity_id))
        )
    ).all()
    return set(rows)


def knowledge_index_status(
    session: Session,
    *,
    tenant_id: UUID,
    embedder: EmbeddingProvider | None = None,
) -> KnowledgeIndexStatus:
    embedder = embedder or resolved_text_embedding_provider(session)
    total_products = int(
        session.scalar(
            select(func.count())
            .select_from(ProductRow)
            .outerjoin(
                ProductCategoryRow,
                (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
                & (ProductCategoryRow.id == ProductRow.category_id)
                & (ProductCategoryRow.status == "ACTIVE"),
            )
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.status == "ACTIVE",
                or_(
                    ProductCategoryRow.id.is_(None),
                    func.trim(ProductCategoryRow.name)
                    != UNCATEGORIZED_CATEGORY_NAME,
                ),
            )
        )
        or 0
    )
    indexed_products = len(
        indexed_product_ids(
            session,
            tenant_id=tenant_id,
            embedder=embedder,
        )
    )
    return KnowledgeIndexStatus(
        total_products=total_products,
        indexed_products=indexed_products,
        pending_products=max(0, total_products - indexed_products),
        model_provider=embedder.identity.provider,
        model_name=embedder.identity.model_name,
        model_version=embedder.identity.model_version,
        dimensions=embedder.identity.dimensions,
    )


def update_knowledge_index(
    session: Session,
    *,
    tenant_id: UUID,
    full_rebuild: bool,
    batch_size: int = 16,
    embedder: EmbeddingProvider | None = None,
    progress_callback: (
        Callable[[int, int, int, UUID | None, str | None], None] | None
    ) = None,
) -> KnowledgeIndexUpdateResult:
    embedder = embedder or resolved_text_embedding_provider(session)
    excluded_product_ids = list(
        session.scalars(
            select(ProductRow.id)
            .join(
                ProductCategoryRow,
                (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
                & (ProductCategoryRow.id == ProductRow.category_id),
            )
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.status == "ACTIVE",
                func.trim(ProductCategoryRow.name)
                == UNCATEGORIZED_CATEGORY_NAME,
            )
        ).all()
    )
    if excluded_product_ids:
        _deactivate_product_knowledge(
            session,
            tenant_id=tenant_id,
            product_ids=excluded_product_ids,
        )
        session.commit()
    all_products = list(
        session.execute(
            select(ProductRow.id, ProductRow.name)
            .outerjoin(
                ProductCategoryRow,
                (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
                & (ProductCategoryRow.id == ProductRow.category_id)
                & (ProductCategoryRow.status == "ACTIVE"),
            )
            .where(
                ProductRow.tenant_id == tenant_id,
                ProductRow.status == "ACTIVE",
                or_(
                    ProductCategoryRow.id.is_(None),
                    func.trim(ProductCategoryRow.name)
                    != UNCATEGORIZED_CATEGORY_NAME,
                ),
            )
            .order_by(ProductRow.id)
        ).all()
    )
    if full_rebuild:
        target_products = all_products
    else:
        current_indexed_ids = indexed_product_ids(
            session,
            tenant_id=tenant_id,
            embedder=embedder,
        )
        target_products = [
            (product_id, product_name)
            for product_id, product_name in all_products
            if product_id not in current_indexed_ids
        ]

    total_targets = len(target_products)
    embedding_count = 0
    if progress_callback is not None:
        first = target_products[0] if target_products else (None, None)
        progress_callback(0, total_targets, 0, first[0], first[1])
        session.commit()
    for start in range(0, total_targets, batch_size):
        batch = target_products[start : start + batch_size]
        results = project_products_knowledge(
            session,
            tenant_id=tenant_id,
            product_ids=[product_id for product_id, _name in batch],
            embedder=embedder,
            force_reembed=full_rebuild,
        )
        embedding_count += sum(result.embeddings for result in results)
        processed = min(start + len(batch), total_targets)
        next_product = (
            target_products[processed]
            if processed < total_targets
            else (None, None)
        )
        if progress_callback is not None:
            progress_callback(
                processed,
                total_targets,
                embedding_count,
                next_product[0],
                next_product[1],
            )
        session.commit()

    status = knowledge_index_status(
        session,
        tenant_id=tenant_id,
        embedder=embedder,
    )
    return KnowledgeIndexUpdateResult(
        mode="FULL_REBUILD" if full_rebuild else "INCREMENTAL",
        processed_products=total_targets,
        total_products=status.total_products,
        indexed_products=status.indexed_products,
        pending_products=status.pending_products,
        embeddings=embedding_count,
        model_provider=status.model_provider,
        model_name=status.model_name,
        model_version=status.model_version,
        dimensions=status.dimensions,
    )
