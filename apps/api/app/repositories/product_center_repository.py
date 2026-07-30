from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from ..ai_data_models import AISourceEvidenceRow
from ..db_models import ImportJobRow, SourceFileRow, SupplierRow
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


@dataclass(frozen=True)
class SkuListRow:
    sku: SkuRow
    product: ProductRow
    category: ProductCategoryRow | None
    public_offer: PublicCatalogOfferRow | None
    source_filename: str | None
    source_imported_at: datetime | None


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
        statement = statement.where(
            or_(
                ProductRow.category_id == category_id,
                ProductRow.category_id.in_(
                    select(ProductCategoryRow.id).where(
                        ProductCategoryRow.tenant_id == tenant_id,
                        ProductCategoryRow.parent_id == category_id,
                    )
                ),
            )
        )
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


def list_categories_by_ids(
    session: Session, *, tenant_id: UUID, category_ids: list[UUID]
) -> list[ProductCategoryRow]:
    if not category_ids:
        return []
    return list(
        session.scalars(
            select(ProductCategoryRow).where(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id.in_(category_ids),
            )
        ).all()
    )


def list_sibling_categories(
    session: Session, *, tenant_id: UUID, parent_id: UUID | None
) -> list[ProductCategoryRow]:
    parent_condition = (
        ProductCategoryRow.parent_id.is_(None)
        if parent_id is None
        else ProductCategoryRow.parent_id == parent_id
    )
    return list(
        session.scalars(
            select(ProductCategoryRow)
            .where(
                ProductCategoryRow.tenant_id == tenant_id,
                parent_condition,
            )
            .order_by(ProductCategoryRow.sort_order, ProductCategoryRow.name)
        ).all()
    )


def find_sibling_category(
    session: Session,
    *,
    tenant_id: UUID,
    parent_id: UUID | None,
    name: str,
    exclude_id: UUID | None = None,
) -> ProductCategoryRow | None:
    conditions = [
        ProductCategoryRow.tenant_id == tenant_id,
        func.lower(ProductCategoryRow.name) == name.casefold().strip(),
    ]
    conditions.append(
        ProductCategoryRow.parent_id.is_(None)
        if parent_id is None
        else ProductCategoryRow.parent_id == parent_id
    )
    if exclude_id is not None:
        conditions.append(ProductCategoryRow.id != exclude_id)
    return session.scalar(select(ProductCategoryRow).where(*conditions))


def list_child_categories(
    session: Session, *, tenant_id: UUID, parent_id: UUID
) -> list[ProductCategoryRow]:
    return list_sibling_categories(
        session, tenant_id=tenant_id, parent_id=parent_id
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


def list_sku_page_rows(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
    category_id: UUID | None,
    statuses: list[str],
    page: int,
    page_size: int,
) -> tuple[list[SkuListRow], int]:
    conditions = [
        SkuRow.tenant_id == tenant_id,
        SkuRow.deleted_at.is_(None),
        ProductRow.tenant_id == tenant_id,
        ProductRow.deleted_at.is_(None),
        ProductRow.status != "ARCHIVED",
    ]
    if statuses:
        conditions.append(SkuRow.status.in_(statuses))
    else:
        conditions.append(SkuRow.status != "ARCHIVED")
    if category_id is not None:
        conditions.append(
            or_(
                ProductRow.category_id == category_id,
                ProductRow.category_id.in_(
                    select(ProductCategoryRow.id).where(
                        ProductCategoryRow.tenant_id == tenant_id,
                        ProductCategoryRow.parent_id == category_id,
                    )
                ),
            )
        )

    normalized = query.casefold().strip()
    if normalized:
        conditions.append(
            or_(
                func.lower(SkuRow.sku_code).contains(normalized, autoescape=True),
                func.lower(func.coalesce(SkuRow.name, "")).contains(
                    normalized, autoescape=True
                ),
                func.lower(func.coalesce(ProductRow.product_code, "")).contains(
                    normalized, autoescape=True
                ),
                func.lower(ProductRow.name).contains(normalized, autoescape=True),
            )
        )

    sku_product_join = and_(
        ProductRow.tenant_id == SkuRow.tenant_id,
        ProductRow.id == SkuRow.product_id,
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SkuRow)
            .join(ProductRow, sku_product_join)
            .where(*conditions)
        )
        or 0
    )

    statement = (
        select(
            SkuRow,
            ProductRow,
            ProductCategoryRow,
            PublicCatalogOfferRow,
            SourceFileRow.original_filename,
            ImportJobRow.completed_at,
        )
        .join(ProductRow, sku_product_join)
        .outerjoin(
            ProductCategoryRow,
            and_(
                ProductCategoryRow.tenant_id == tenant_id,
                ProductCategoryRow.id == ProductRow.category_id,
                ProductCategoryRow.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            PublicCatalogOfferRow,
            and_(
                PublicCatalogOfferRow.tenant_id == tenant_id,
                PublicCatalogOfferRow.sku_id == SkuRow.id,
                PublicCatalogOfferRow.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            ImportJobRow,
            and_(
                ImportJobRow.tenant_id == tenant_id,
                ImportJobRow.id == SkuRow.latest_import_job_id,
                ImportJobRow.deleted_at.is_(None),
            ),
        )
        .outerjoin(
            SourceFileRow,
            and_(
                SourceFileRow.tenant_id == tenant_id,
                SourceFileRow.id == ImportJobRow.source_file_id,
                SourceFileRow.deleted_at.is_(None),
            ),
        )
        .where(*conditions)
    )
    if normalized:
        statement = statement.order_by(
            case(
                (func.lower(SkuRow.sku_code) == normalized, 0),
                (
                    func.lower(func.coalesce(ProductRow.product_code, ""))
                    == normalized,
                    1,
                ),
                else_=2,
            ),
            SkuRow.updated_at.desc(),
            SkuRow.id,
        )
    else:
        statement = statement.order_by(SkuRow.updated_at.desc(), SkuRow.id)
    rows = session.execute(
        statement.limit(page_size).offset((page - 1) * page_size)
    ).all()
    return (
        [
            SkuListRow(
                sku=sku,
                product=product,
                category=category,
                public_offer=public_offer,
                source_filename=source_filename,
                source_imported_at=source_imported_at,
            )
            for (
                sku,
                product,
                category,
                public_offer,
                source_filename,
                source_imported_at,
            ) in rows
        ],
        total,
    )


def list_supplier_rows_for_sku_page(
    session: Session,
    *,
    tenant_id: UUID,
    sku_ids: set[UUID],
    product_ids: set[UUID],
) -> list[tuple[SupplierProductRow, SupplierRow]]:
    if not sku_ids:
        return []
    return list(
        session.execute(
            select(SupplierProductRow, SupplierRow)
            .join(
                SupplierRow,
                and_(
                    SupplierRow.tenant_id == tenant_id,
                    SupplierRow.id == SupplierProductRow.supplier_id,
                    SupplierRow.deleted_at.is_(None),
                ),
            )
            .where(
                SupplierProductRow.tenant_id == tenant_id,
                SupplierProductRow.deleted_at.is_(None),
                or_(
                    SupplierProductRow.sku_id.in_(sku_ids),
                    and_(
                        SupplierProductRow.sku_id.is_(None),
                        SupplierProductRow.product_id.in_(product_ids),
                    ),
                ),
            )
            .order_by(
                case((SupplierProductRow.sku_id.is_(None), 1), else_=0),
                SupplierRow.name,
                SupplierProductRow.id,
            )
        ).all()
    )


def list_suppliers_by_ids(
    session: Session,
    *,
    tenant_id: UUID,
    supplier_ids: set[str],
) -> list[SupplierRow]:
    if not supplier_ids:
        return []
    return list(
        session.scalars(
            select(SupplierRow).where(
                SupplierRow.tenant_id == tenant_id,
                SupplierRow.id.in_(supplier_ids),
                SupplierRow.deleted_at.is_(None),
            )
        ).all()
    )


def list_image_statuses_for_products(
    session: Session,
    *,
    tenant_id: UUID,
    product_ids: set[UUID],
) -> list[tuple[UUID, str]]:
    if not product_ids:
        return []
    return [
        (product_id, approval_status)
        for product_id, approval_status in session.execute(
            select(ProductImageRow.product_id, ProductImageRow.approval_status)
            .where(
                ProductImageRow.tenant_id == tenant_id,
                ProductImageRow.product_id.in_(product_ids),
                ProductImageRow.deleted_at.is_(None),
            )
            .order_by(ProductImageRow.product_id, ProductImageRow.sort_order, ProductImageRow.id)
        ).all()
    ]


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
