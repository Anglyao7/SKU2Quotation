from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session

from ..ai_data_models import AISourceEvidenceRow
from ..db_models import ImportJobRow, SupplierRow
from ..product_center_models import (
    AttributeDefinitionRow,
    ProductAuditEventRow,
    SkuRow,
    SupplierPriceRow,
)
from ..public_catalog_models import PublicCatalogOfferRow
from ..product_intelligence_models import ProductCandidateDecisionRow, ProductFieldCandidateRow
from ..product_supplier_models import (
    ProductAttributeRow,
    ProductCategoryRow,
    ProductImageRow,
    ProductRow,
    SupplierProductRow,
)


def list_product_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    category_id: UUID | None,
    supplier_id: str | None,
    statuses: list[str],
    approved_images_only: bool,
    limit: int,
) -> list[ProductRow]:
    statement = select(ProductRow).where(ProductRow.tenant_id == tenant_id)
    if statuses:
        statement = statement.where(ProductRow.status.in_(statuses))
    else:
        statement = statement.where(ProductRow.status != "ARCHIVED")
    if category_id is not None:
        statement = statement.where(ProductRow.category_id == category_id)
    if supplier_id:
        statement = statement.where(
            exists(
                select(SupplierProductRow.id).where(
                    SupplierProductRow.tenant_id == tenant_id,
                    SupplierProductRow.product_id == ProductRow.id,
                    SupplierProductRow.supplier_id == supplier_id,
                    SupplierProductRow.deleted_at.is_(None),
                )
            )
        )
    if approved_images_only:
        statement = statement.where(
            exists(
                select(ProductImageRow.id).where(
                    ProductImageRow.tenant_id == tenant_id,
                    ProductImageRow.product_id == ProductRow.id,
                    ProductImageRow.approval_status == "APPROVED",
                    ProductImageRow.deleted_at.is_(None),
                )
            )
        )
    normalized = query.casefold().strip()
    if normalized:
        exact_sku = exists(
            select(SkuRow.id).where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.product_id == ProductRow.id,
                func.lower(SkuRow.sku_code) == normalized,
                SkuRow.deleted_at.is_(None),
            )
        )
        contains_sku = exists(
            select(SkuRow.id).where(
                SkuRow.tenant_id == tenant_id,
                SkuRow.product_id == ProductRow.id,
                func.lower(SkuRow.sku_code).contains(normalized),
                SkuRow.deleted_at.is_(None),
            )
        )
        statement = statement.where(
            or_(
                func.lower(func.coalesce(ProductRow.product_code, "")).contains(normalized),
                func.lower(ProductRow.name).contains(normalized),
                contains_sku,
            )
        ).order_by(
            case(
                (
                    func.lower(func.coalesce(ProductRow.product_code, "")) == normalized,
                    0,
                ),
                (exact_sku, 0),
                else_=1,
            ),
            ProductRow.updated_at.desc(),
            ProductRow.id,
        )
    else:
        statement = statement.order_by(ProductRow.updated_at.desc(), ProductRow.id)
    return list(session.scalars(statement.limit(limit)).all())


def get_product_row(session: Session, *, tenant_id: UUID, product_id: UUID) -> ProductRow | None:
    return session.scalar(
        select(ProductRow).where(
            ProductRow.tenant_id == tenant_id,
            ProductRow.id == product_id,
        )
    )


def get_category(
    session: Session, *, tenant_id: UUID, category_id: UUID | None
) -> ProductCategoryRow | None:
    if category_id is None:
        return None
    return session.scalar(
        select(ProductCategoryRow).where(
            ProductCategoryRow.tenant_id == tenant_id,
            ProductCategoryRow.id == category_id,
        )
    )


def list_categories(session: Session, *, tenant_id: UUID) -> list[ProductCategoryRow]:
    return list(
        session.scalars(
            select(ProductCategoryRow)
            .where(ProductCategoryRow.tenant_id == tenant_id)
            .order_by(ProductCategoryRow.path, ProductCategoryRow.sort_order, ProductCategoryRow.name)
        ).all()
    )


def list_attributes(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> list[ProductAttributeRow]:
    return list(
        session.scalars(
            select(ProductAttributeRow)
            .where(
                ProductAttributeRow.tenant_id == tenant_id,
                ProductAttributeRow.product_id == product_id,
            )
            .order_by(ProductAttributeRow.attribute_key, ProductAttributeRow.id)
        ).all()
    )


def list_images(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> list[ProductImageRow]:
    return list(
        session.scalars(
            select(ProductImageRow)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.product_id == product_id,
            )
            .order_by(
                case((ProductImageRow.image_role == "MAIN", 0), else_=1),
                ProductImageRow.sort_order,
                ProductImageRow.id,
            )
        ).all()
    )


def list_skus(session: Session, *, tenant_id: UUID, product_id: UUID) -> list[SkuRow]:
    return list(
        session.scalars(
            select(SkuRow)
            .where(SkuRow.tenant_id == tenant_id, SkuRow.product_id == product_id)
            .order_by(SkuRow.sku_code, SkuRow.id)
        ).all()
    )


def get_sku(session: Session, *, tenant_id: UUID, sku_id: UUID) -> SkuRow | None:
    return session.scalar(select(SkuRow).where(SkuRow.tenant_id == tenant_id, SkuRow.id == sku_id))


def get_public_offer(
    session: Session, *, tenant_id: UUID, sku_id: UUID
) -> PublicCatalogOfferRow | None:
    return session.scalar(
        select(PublicCatalogOfferRow).where(
            PublicCatalogOfferRow.tenant_id == tenant_id,
            PublicCatalogOfferRow.sku_id == sku_id,
        )
    )


def list_public_offers_for_product(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> list[PublicCatalogOfferRow]:
    return list(
        session.scalars(
            select(PublicCatalogOfferRow)
            .join(
                SkuRow,
                (SkuRow.tenant_id == PublicCatalogOfferRow.tenant_id)
                & (SkuRow.id == PublicCatalogOfferRow.sku_id),
            )
            .where(
                PublicCatalogOfferRow.tenant_id == tenant_id,
                SkuRow.tenant_id == tenant_id,
                SkuRow.product_id == product_id,
            )
            .order_by(SkuRow.sku_code, PublicCatalogOfferRow.id)
        ).all()
    )


def sku_code_exists(session: Session, *, tenant_id: UUID, sku_code: str) -> bool:
    return session.scalar(
        select(func.count()).select_from(SkuRow).where(
            SkuRow.tenant_id == tenant_id,
            func.lower(SkuRow.sku_code) == sku_code.casefold(),
        )
    ) > 0


def list_sources(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> list[tuple[SupplierProductRow, SupplierRow]]:
    return list(
        session.execute(
            select(SupplierProductRow, SupplierRow)
            .join(
                SupplierRow,
                (SupplierRow.tenant_id == SupplierProductRow.tenant_id)
                & (SupplierRow.id == SupplierProductRow.supplier_id),
            )
            .where(
                SupplierProductRow.tenant_id == tenant_id,
                SupplierProductRow.product_id == product_id,
            )
            .order_by(SupplierProductRow.status, SupplierRow.name)
        ).all()
    )


def list_prices_for_product(
    session: Session, *, tenant_id: UUID, product_id: UUID
) -> list[tuple[SupplierPriceRow, SupplierProductRow, SupplierRow]]:
    return list(
        session.execute(
            select(SupplierPriceRow, SupplierProductRow, SupplierRow)
            .join(
                SupplierProductRow,
                (SupplierProductRow.tenant_id == SupplierPriceRow.tenant_id)
                & (SupplierProductRow.id == SupplierPriceRow.supplier_product_id),
            )
            .join(
                SupplierRow,
                (SupplierRow.tenant_id == SupplierProductRow.tenant_id)
                & (SupplierRow.id == SupplierProductRow.supplier_id),
            )
            .where(
                SupplierPriceRow.tenant_id == tenant_id,
                SupplierProductRow.product_id == product_id,
            )
            .order_by(SupplierPriceRow.valid_from.desc(), SupplierPriceRow.created_at.desc())
        ).all()
    )


def get_supplier_product(
    session: Session, *, tenant_id: UUID, supplier_product_id: UUID
) -> SupplierProductRow | None:
    return session.scalar(
        select(SupplierProductRow).where(
            SupplierProductRow.tenant_id == tenant_id,
            SupplierProductRow.id == supplier_product_id,
        )
    )


def get_price(
    session: Session, *, tenant_id: UUID, price_id: UUID
) -> SupplierPriceRow | None:
    return session.scalar(
        select(SupplierPriceRow).where(
            SupplierPriceRow.tenant_id == tenant_id,
            SupplierPriceRow.id == price_id,
        )
    )


def list_attribute_definitions(
    session: Session, *, tenant_id: UUID, category_id: UUID | None
) -> list[AttributeDefinitionRow]:
    statement = select(AttributeDefinitionRow).where(
        AttributeDefinitionRow.tenant_id == tenant_id
    )
    if category_id is not None:
        statement = statement.where(
            or_(
                AttributeDefinitionRow.category_id == category_id,
                AttributeDefinitionRow.category_id.is_(None),
            )
        )
    return list(
        session.scalars(
            statement.order_by(
                AttributeDefinitionRow.category_id,
                AttributeDefinitionRow.attribute_key,
            )
        ).all()
    )


def list_audit_events(
    session: Session, *, tenant_id: UUID, product_id: UUID, limit: int = 100
) -> list[ProductAuditEventRow]:
    return list(
        session.scalars(
            select(ProductAuditEventRow)
            .where(
                ProductAuditEventRow.tenant_id == tenant_id,
                ProductAuditEventRow.product_id == product_id,
            )
            .order_by(ProductAuditEventRow.occurred_at.desc(), ProductAuditEventRow.id.desc())
            .limit(limit)
        ).all()
    )


def list_review_candidates(
    session: Session, *, tenant_id: UUID, limit: int
) -> list[tuple[ProductFieldCandidateRow, AISourceEvidenceRow]]:
    return list(
        session.execute(
            select(ProductFieldCandidateRow, AISourceEvidenceRow)
            .join(
                AISourceEvidenceRow,
                (AISourceEvidenceRow.tenant_id == ProductFieldCandidateRow.tenant_id)
                & (AISourceEvidenceRow.id == ProductFieldCandidateRow.source_evidence_id),
            )
            .where(ProductFieldCandidateRow.tenant_id == tenant_id)
            .order_by(
                ProductFieldCandidateRow.created_at.desc(),
                ProductFieldCandidateRow.candidate_index,
                ProductFieldCandidateRow.field_key,
            )
            .limit(limit)
        ).all()
    )


def review_decisions_for_tasks(
    session: Session, *, tenant_id: UUID, task_ids: set[UUID]
) -> list[ProductCandidateDecisionRow]:
    if not task_ids:
        return []
    return list(
        session.scalars(
            select(ProductCandidateDecisionRow)
            .where(
                ProductCandidateDecisionRow.tenant_id == tenant_id,
                ProductCandidateDecisionRow.ai_task_id.in_(task_ids),
            )
            .order_by(ProductCandidateDecisionRow.created_at.desc())
        ).all()
    )


def supplier_name_for_source(
    session: Session, *, tenant_id: UUID, source_file_id: str | None
) -> str:
    if not source_file_id:
        return "Unassigned supplier"
    value = session.scalar(
        select(ImportJobRow.supplier_name)
        .where(
            ImportJobRow.tenant_id == tenant_id,
            ImportJobRow.source_file_id == source_file_id,
        )
        .order_by(ImportJobRow.created_at.desc())
        .limit(1)
    )
    return value or "Unassigned supplier"
