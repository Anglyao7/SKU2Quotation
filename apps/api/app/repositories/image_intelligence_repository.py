from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..image_intelligence_models import ImageEmbeddingRow, ImageSearchRow, VisionObservationRow
from ..product_supplier_models import ProductImageRow, ProductRow
from ..services.embedding import cosine_similarity


def get_product_image(session: Session, *, tenant_id: UUID, image_id: UUID) -> tuple[ProductImageRow, ProductRow] | None:
    return session.execute(select(ProductImageRow, ProductRow).join(ProductRow, ProductRow.id == ProductImageRow.product_id).where(ProductImageRow.tenant_id == tenant_id, ProductImageRow.id == image_id, ProductImageRow.deleted_at.is_(None), ProductRow.tenant_id == tenant_id, ProductRow.deleted_at.is_(None))).one_or_none()


def get_projection(session: Session, *, tenant_id: UUID, image_id: UUID, provider: str, model: str, version: str, content_hash: str) -> tuple[ImageEmbeddingRow, VisionObservationRow] | None:
    return session.execute(select(ImageEmbeddingRow, VisionObservationRow).join(VisionObservationRow, (VisionObservationRow.tenant_id == ImageEmbeddingRow.tenant_id) & (VisionObservationRow.product_image_id == ImageEmbeddingRow.product_image_id) & (VisionObservationRow.content_hash == ImageEmbeddingRow.content_hash) & (VisionObservationRow.model_provider == ImageEmbeddingRow.model_provider) & (VisionObservationRow.model_name == ImageEmbeddingRow.model_name) & (VisionObservationRow.model_version == ImageEmbeddingRow.model_version)).where(ImageEmbeddingRow.tenant_id == tenant_id, ImageEmbeddingRow.product_image_id == image_id, ImageEmbeddingRow.model_provider == provider, ImageEmbeddingRow.model_name == model, ImageEmbeddingRow.model_version == version, ImageEmbeddingRow.content_hash == content_hash, ImageEmbeddingRow.deleted_at.is_(None))).one_or_none()


def list_active_corpus(session: Session, *, tenant_id: UUID, provider: str, model: str, version: str) -> list[tuple[ImageEmbeddingRow, ProductImageRow, ProductRow]]:
    return session.execute(select(ImageEmbeddingRow, ProductImageRow, ProductRow).join(ProductImageRow, (ProductImageRow.tenant_id == ImageEmbeddingRow.tenant_id) & (ProductImageRow.id == ImageEmbeddingRow.product_image_id)).join(ProductRow, (ProductRow.tenant_id == ImageEmbeddingRow.tenant_id) & (ProductRow.id == ImageEmbeddingRow.product_id)).where(ImageEmbeddingRow.tenant_id == tenant_id, ImageEmbeddingRow.model_provider == provider, ImageEmbeddingRow.model_name == model, ImageEmbeddingRow.model_version == version, ImageEmbeddingRow.status == "ACTIVE", ImageEmbeddingRow.deleted_at.is_(None), ProductImageRow.approval_status == "APPROVED", ProductImageRow.deleted_at.is_(None), ProductRow.status == "ACTIVE", ProductRow.deleted_at.is_(None))).all()


def search_active_corpus(session: Session, *, tenant_id: UUID, provider: str, model: str, version: str, query_vector: list[float], limit: int) -> list[dict[str, object]]:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        vector_literal = "[" + ",".join(f"{value:.12g}" for value in query_vector) + "]"
        rows = session.execute(text("""
            SELECT e.product_id, e.product_image_id, p.name AS product_name,
                   p.product_code, e.content_hash, e.quality_score,
                   1 - (e.embedding::vector(384) <=> CAST(:query_vector AS vector(384))) AS similarity
            FROM image_embeddings e
            JOIN product_images i ON i.tenant_id=e.tenant_id AND i.id=e.product_image_id
            JOIN products p ON p.tenant_id=e.tenant_id AND p.id=e.product_id
            WHERE e.tenant_id=:tenant_id AND e.model_provider=:provider
              AND e.model_name=:model AND e.model_version=:version
              AND e.dimensions=384 AND e.status='ACTIVE' AND e.deleted_at IS NULL
              AND i.approval_status='APPROVED' AND i.deleted_at IS NULL
              AND p.status='ACTIVE' AND p.deleted_at IS NULL
            ORDER BY e.embedding::vector(384) <=> CAST(:query_vector AS vector(384))
            LIMIT :limit
        """), {"query_vector": vector_literal, "tenant_id": tenant_id, "provider": provider, "model": model, "version": version, "limit": limit}).mappings().all()
        return [dict(row) for row in rows]
    candidates = []
    for embedding, image, product in list_active_corpus(session, tenant_id=tenant_id, provider=provider, model=model, version=version):
        candidates.append({"product_id": product.id, "product_image_id": image.id, "product_name": product.name, "product_code": product.product_code, "content_hash": embedding.content_hash, "quality_score": float(embedding.quality_score), "similarity": cosine_similarity(query_vector, list(embedding.embedding))})
    return sorted(candidates, key=lambda row: float(row["similarity"]), reverse=True)[:limit]


def list_expired_searches(session: Session, *, tenant_id: UUID, now: datetime) -> list[ImageSearchRow]:
    return session.scalars(select(ImageSearchRow).where(ImageSearchRow.tenant_id == tenant_id, ImageSearchRow.status != "EXPIRED", ImageSearchRow.expires_at <= now, ImageSearchRow.deleted_at.is_(None))).all()
