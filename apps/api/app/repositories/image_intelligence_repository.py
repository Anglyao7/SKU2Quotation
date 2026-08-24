from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, exists, func, or_, select, text
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from ..image_intelligence_models import ImageEmbeddingRow, ImageSearchRow, VisionObservationRow
from ..product_center_models import SkuRow
from ..public_catalog_models import PublicCatalogOfferRow
from ..product_supplier_models import ProductCategoryRow, ProductImageRow, ProductRow
from ..services.embedding import cosine_similarity


SUPPORTED_IMAGE_VECTOR_DIMENSIONS = frozenset(
    {256, 384, 512, 768, 1024, 1536, 2048, 2560}
)


def get_product_image(session: Session, *, tenant_id: UUID, image_id: UUID) -> tuple[ProductImageRow, ProductRow] | None:
    return session.execute(select(ProductImageRow, ProductRow).join(ProductRow, ProductRow.id == ProductImageRow.product_id).where(ProductImageRow.tenant_id == tenant_id, ProductImageRow.id == image_id, ProductImageRow.deleted_at.is_(None), ProductRow.tenant_id == tenant_id, ProductRow.deleted_at.is_(None))).one_or_none()


def get_projection(session: Session, *, tenant_id: UUID, image_id: UUID, provider: str, model: str, version: str, content_hash: str) -> tuple[ImageEmbeddingRow, VisionObservationRow] | None:
    return session.execute(select(ImageEmbeddingRow, VisionObservationRow).join(VisionObservationRow, (VisionObservationRow.tenant_id == ImageEmbeddingRow.tenant_id) & (VisionObservationRow.product_image_id == ImageEmbeddingRow.product_image_id) & (VisionObservationRow.content_hash == ImageEmbeddingRow.content_hash) & (VisionObservationRow.model_provider == ImageEmbeddingRow.model_provider) & (VisionObservationRow.model_name == ImageEmbeddingRow.model_name) & (VisionObservationRow.model_version == ImageEmbeddingRow.model_version)).where(ImageEmbeddingRow.tenant_id == tenant_id, ImageEmbeddingRow.product_image_id == image_id, ImageEmbeddingRow.model_provider == provider, ImageEmbeddingRow.model_name == model, ImageEmbeddingRow.model_version == version, ImageEmbeddingRow.content_hash == content_hash, ImageEmbeddingRow.deleted_at.is_(None))).one_or_none()


def list_active_corpus(session: Session, *, tenant_id: UUID, provider: str, model: str, version: str) -> list[tuple[ImageEmbeddingRow, ProductImageRow, ProductRow]]:
    return session.execute(select(ImageEmbeddingRow, ProductImageRow, ProductRow).join(ProductImageRow, (ProductImageRow.tenant_id == ImageEmbeddingRow.tenant_id) & (ProductImageRow.id == ImageEmbeddingRow.product_image_id)).join(ProductRow, (ProductRow.tenant_id == ImageEmbeddingRow.tenant_id) & (ProductRow.id == ImageEmbeddingRow.product_id)).where(ImageEmbeddingRow.tenant_id == tenant_id, ImageEmbeddingRow.model_provider == provider, ImageEmbeddingRow.model_name == model, ImageEmbeddingRow.model_version == version, ImageEmbeddingRow.content_hash == ProductImageRow.sha256, ImageEmbeddingRow.status == "ACTIVE", ImageEmbeddingRow.deleted_at.is_(None), ProductImageRow.approval_status == "APPROVED", ProductImageRow.deleted_at.is_(None), ProductRow.status == "ACTIVE", ProductRow.deleted_at.is_(None))).all()


def list_index_target_images(
    session: Session,
    *,
    tenant_id: UUID,
    provider: str,
    model: str,
    version: str,
    dimensions: int,
    full_rebuild: bool,
    image_ids: list[UUID] | None = None,
) -> list[tuple[UUID, str]]:
    current_embedding = aliased(ImageEmbeddingRow)
    statement = (
        select(ProductImageRow.id, ProductRow.name)
        .join(
            ProductRow,
            (ProductRow.tenant_id == ProductImageRow.tenant_id)
            & (ProductRow.id == ProductImageRow.product_id),
        )
        .where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.approval_status == "APPROVED",
            ProductImageRow.deleted_at.is_(None),
            ProductRow.tenant_id == tenant_id,
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
        )
        .order_by(ProductImageRow.product_id, ProductImageRow.sort_order, ProductImageRow.id)
    )
    if image_ids is not None:
        if not image_ids:
            return []
        statement = statement.where(ProductImageRow.id.in_(image_ids))
    if not full_rebuild:
        statement = statement.where(
            ~exists(
                select(current_embedding.id).where(
                    current_embedding.tenant_id == ProductImageRow.tenant_id,
                    current_embedding.product_image_id == ProductImageRow.id,
                    current_embedding.content_hash == ProductImageRow.sha256,
                    current_embedding.model_provider == provider,
                    current_embedding.model_name == model,
                    current_embedding.model_version == version,
                    current_embedding.dimensions == dimensions,
                    current_embedding.status == "ACTIVE",
                    current_embedding.deleted_at.is_(None),
                )
            )
        )
    return [(UUID(str(row[0])), str(row[1])) for row in session.execute(statement).all()]


def image_index_status(
    session: Session,
    *,
    tenant_id: UUID,
    provider: str,
    model: str,
    version: str,
    dimensions: int,
) -> dict[str, int]:
    base = (
        select(ProductImageRow.id, ProductImageRow.product_id, ProductImageRow.sha256)
        .join(
            ProductRow,
            (ProductRow.tenant_id == ProductImageRow.tenant_id)
            & (ProductRow.id == ProductImageRow.product_id),
        )
        .where(
            ProductImageRow.tenant_id == tenant_id,
            ProductImageRow.approval_status == "APPROVED",
            ProductImageRow.deleted_at.is_(None),
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
        )
        .subquery()
    )
    total_images = int(session.scalar(select(func.count()).select_from(base)) or 0)
    indexed = (
        select(ImageEmbeddingRow.product_image_id, ImageEmbeddingRow.product_id)
        .join(base, base.c.id == ImageEmbeddingRow.product_image_id)
        .where(
            ImageEmbeddingRow.tenant_id == tenant_id,
            ImageEmbeddingRow.model_provider == provider,
            ImageEmbeddingRow.model_name == model,
            ImageEmbeddingRow.model_version == version,
            ImageEmbeddingRow.dimensions == dimensions,
            ImageEmbeddingRow.content_hash == base.c.sha256,
            ImageEmbeddingRow.status == "ACTIVE",
            ImageEmbeddingRow.deleted_at.is_(None),
        )
        .distinct()
        .subquery()
    )
    indexed_images = int(session.scalar(select(func.count()).select_from(indexed)) or 0)
    indexed_products = int(
        session.scalar(select(func.count(func.distinct(indexed.c.product_id)))) or 0
    )
    return {
        "total_images": total_images,
        "indexed_images": indexed_images,
        "pending_images": max(0, total_images - indexed_images),
        "indexed_products": indexed_products,
    }


def _published_product_ids(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> set[UUID]:
    return {
        UUID(str(value))
        for value in session.scalars(
            select(SkuRow.product_id)
            .join(
                PublicCatalogOfferRow,
                (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
                & (PublicCatalogOfferRow.sku_id == SkuRow.id),
            )
            .where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.status == "ACTIVE",
                PublicCatalogOfferRow.publication_status == "PUBLISHED",
                or_(
                    PublicCatalogOfferRow.valid_from.is_(None),
                    PublicCatalogOfferRow.valid_from <= now,
                ),
                or_(
                    PublicCatalogOfferRow.valid_to.is_(None),
                    PublicCatalogOfferRow.valid_to >= now,
                ),
                PublicCatalogOfferRow.deleted_at.is_(None),
            )
            .distinct()
        ).all()
    }


def has_active_corpus(
    session: Session,
    *,
    tenant_id: UUID,
    provider: str,
    model: str,
    version: str,
    dimensions: int,
    published_only: bool = False,
    allowed_product_ids: set[UUID] | None = None,
    category: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Check corpus availability without creating a paid query embedding."""

    if allowed_product_ids is not None and not allowed_product_ids:
        return False
    statement = (
        select(ImageEmbeddingRow.id)
        .join(
            ProductImageRow,
            (ProductImageRow.tenant_id == ImageEmbeddingRow.tenant_id)
            & (ProductImageRow.id == ImageEmbeddingRow.product_image_id),
        )
        .join(
            ProductRow,
            (ProductRow.tenant_id == ImageEmbeddingRow.tenant_id)
            & (ProductRow.id == ImageEmbeddingRow.product_id),
        )
        .where(
            ImageEmbeddingRow.tenant_id == tenant_id,
            ImageEmbeddingRow.model_provider == provider,
            ImageEmbeddingRow.model_name == model,
            ImageEmbeddingRow.model_version == version,
            ImageEmbeddingRow.dimensions == dimensions,
            ImageEmbeddingRow.content_hash == ProductImageRow.sha256,
            ImageEmbeddingRow.status == "ACTIVE",
            ImageEmbeddingRow.deleted_at.is_(None),
            ProductImageRow.approval_status == "APPROVED",
            ProductImageRow.deleted_at.is_(None),
            ProductRow.status == "ACTIVE",
            ProductRow.deleted_at.is_(None),
        )
    )
    if allowed_product_ids is not None:
        statement = statement.where(
            ImageEmbeddingRow.product_id.in_(allowed_product_ids)
        )
    if category:
        normalized_category = category.casefold().strip()
        category_path = func.lower(
            func.coalesce(ProductCategoryRow.path, ProductCategoryRow.name)
        )
        statement = statement.join(
            ProductCategoryRow,
            (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
            & (ProductCategoryRow.id == ProductRow.category_id),
        ).where(
            or_(
                func.lower(ProductCategoryRow.name) == normalized_category,
                category_path == normalized_category,
                category_path.startswith(
                    f"{normalized_category}/",
                    autoescape=True,
                ),
            )
        )
    if published_only:
        effective_now = now or datetime.now().astimezone()
        statement = statement.where(
            exists(
                select(PublicCatalogOfferRow.id)
                .select_from(SkuRow)
                .join(
                    PublicCatalogOfferRow,
                    (PublicCatalogOfferRow.tenant_id == SkuRow.tenant_id)
                    & (PublicCatalogOfferRow.sku_id == SkuRow.id),
                )
                .where(
                    SkuRow.tenant_id == ImageEmbeddingRow.tenant_id,
                    SkuRow.product_id == ImageEmbeddingRow.product_id,
                    SkuRow.status == "ACTIVE",
                    PublicCatalogOfferRow.publication_status == "PUBLISHED",
                    or_(
                        PublicCatalogOfferRow.valid_from.is_(None),
                        PublicCatalogOfferRow.valid_from <= effective_now,
                    ),
                    or_(
                        PublicCatalogOfferRow.valid_to.is_(None),
                        PublicCatalogOfferRow.valid_to >= effective_now,
                    ),
                    PublicCatalogOfferRow.deleted_at.is_(None),
                )
            )
        )
    return session.scalar(statement.limit(1)) is not None


def search_active_corpus(
    session: Session,
    *,
    tenant_id: UUID,
    provider: str,
    model: str,
    version: str,
    dimensions: int,
    query_vector: list[float],
    limit: int,
    published_only: bool = False,
    allowed_product_ids: set[UUID] | None = None,
    category: str | None = None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    if dimensions not in SUPPORTED_IMAGE_VECTOR_DIMENSIONS:
        raise ValueError("unsupported image vector dimensions")
    if allowed_product_ids is not None and not allowed_product_ids:
        return []
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        vector_literal = "[" + ",".join(f"{value:.12g}" for value in query_vector) + "]"
        publication_filter = ""
        category_join = ""
        category_filter = ""
        parameters: dict[str, object] = {
            "query_vector": vector_literal,
            "tenant_id": tenant_id,
            "provider": provider,
            "model": model,
            "version": version,
            "dimensions": dimensions,
            "limit": limit,
        }
        if published_only:
            publication_filter = """
              AND EXISTS (
                SELECT 1
                FROM skus s
                JOIN public_catalog_offers o
                  ON o.tenant_id=s.tenant_id AND o.sku_id=s.id
                WHERE s.tenant_id=e.tenant_id AND s.product_id=e.product_id
                  AND s.status='ACTIVE' AND s.deleted_at IS NULL
                  AND o.publication_status='PUBLISHED' AND o.deleted_at IS NULL
                  AND (o.valid_from IS NULL OR o.valid_from <= CURRENT_TIMESTAMP)
                  AND (o.valid_to IS NULL OR o.valid_to >= CURRENT_TIMESTAMP)
              )
            """
        allowed_filter = ""
        if allowed_product_ids is not None:
            allowed_filter = " AND e.product_id IN :allowed_product_ids"
            parameters["allowed_product_ids"] = list(allowed_product_ids)
        if category:
            normalized_category = category.casefold().strip()
            escaped_category = (
                normalized_category.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            category_join = """
              JOIN product_categories c
                ON c.tenant_id=p.tenant_id AND c.id=p.category_id
               AND c.deleted_at IS NULL
            """
            category_filter = """
              AND (
                lower(c.name)=:category
                OR lower(COALESCE(c.path, c.name))=:category
                OR lower(COALESCE(c.path, c.name)) LIKE :category_prefix ESCAPE '\\'
              )
            """
            parameters["category"] = normalized_category
            parameters["category_prefix"] = f"{escaped_category}/%"
        sql = f"""
            SELECT e.product_id, e.product_image_id, p.name AS product_name,
                   p.product_code, e.content_hash, e.quality_score,
                   1 - (e.embedding::vector({dimensions}) <=> CAST(:query_vector AS vector({dimensions}))) AS similarity
            FROM image_embeddings e
            JOIN product_images i ON i.tenant_id=e.tenant_id AND i.id=e.product_image_id
            JOIN products p ON p.tenant_id=e.tenant_id AND p.id=e.product_id
            {category_join}
            WHERE e.tenant_id=:tenant_id AND e.model_provider=:provider
              AND e.model_name=:model AND e.model_version=:version
              AND e.dimensions=:dimensions AND e.status='ACTIVE' AND e.deleted_at IS NULL
              AND i.approval_status='APPROVED' AND i.deleted_at IS NULL
              AND e.content_hash=i.sha256
              AND p.status='ACTIVE' AND p.deleted_at IS NULL
              {publication_filter}
              {allowed_filter}
              {category_filter}
            ORDER BY e.embedding::vector({dimensions}) <=> CAST(:query_vector AS vector({dimensions}))
            LIMIT :limit
        """
        statement = text(sql)
        if allowed_product_ids is not None:
            statement = statement.bindparams(
                bindparam("allowed_product_ids", expanding=True)
            )
        rows = session.execute(statement, parameters).mappings().all()
        return [dict(row) for row in rows]
    published_ids = (
        _published_product_ids(
            session,
            tenant_id=tenant_id,
            now=now or datetime.now().astimezone(),
        )
        if published_only
        else None
    )
    category_ids = None
    if category:
        normalized_category = category.casefold().strip()
        category_path = func.lower(
            func.coalesce(ProductCategoryRow.path, ProductCategoryRow.name)
        )
        category_ids = {
            UUID(str(value))
            for value in session.scalars(
                select(ProductRow.id)
                .join(
                    ProductCategoryRow,
                    (ProductCategoryRow.tenant_id == ProductRow.tenant_id)
                    & (ProductCategoryRow.id == ProductRow.category_id),
                )
                .where(
                    ProductRow.tenant_id == tenant_id,
                    or_(
                        func.lower(ProductCategoryRow.name) == normalized_category,
                        category_path == normalized_category,
                        category_path.startswith(
                            f"{normalized_category}/",
                            autoescape=True,
                        ),
                    ),
                )
            ).all()
        }
    candidates = []
    for embedding, image, product in list_active_corpus(session, tenant_id=tenant_id, provider=provider, model=model, version=version):
        if embedding.dimensions != dimensions:
            continue
        if published_ids is not None and product.id not in published_ids:
            continue
        if allowed_product_ids is not None and product.id not in allowed_product_ids:
            continue
        if category_ids is not None and product.id not in category_ids:
            continue
        candidates.append({"product_id": product.id, "product_image_id": image.id, "product_name": product.name, "product_code": product.product_code, "content_hash": embedding.content_hash, "quality_score": float(embedding.quality_score), "similarity": cosine_similarity(query_vector, list(embedding.embedding))})
    return sorted(candidates, key=lambda row: float(row["similarity"]), reverse=True)[:limit]


def list_expired_searches(session: Session, *, tenant_id: UUID, now: datetime) -> list[ImageSearchRow]:
    return session.scalars(select(ImageSearchRow).where(ImageSearchRow.tenant_id == tenant_id, ImageSearchRow.status != "EXPIRED", ImageSearchRow.expires_at <= now, ImageSearchRow.deleted_at.is_(None))).all()
