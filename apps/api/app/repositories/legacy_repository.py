from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db_models import ImportJobRow, ReviewItemRow, SourceFileRow, SupplierRow


def find_supplier(session: Session, *, tenant_id: UUID, supplier_id: str) -> SupplierRow | None:
    return session.scalar(
        select(SupplierRow).where(
            SupplierRow.tenant_id == tenant_id,
            SupplierRow.id == supplier_id,
        )
    )


def add_import_records(
    session: Session,
    *,
    source_values: dict[str, Any],
    job_values: dict[str, Any],
) -> tuple[SourceFileRow, ImportJobRow]:
    source = SourceFileRow(**source_values)
    job = ImportJobRow(**job_values)
    session.add_all([source, job])
    return source, job


def get_review_item(
    session: Session,
    *,
    tenant_id: UUID,
    item_id: str,
) -> ReviewItemRow | None:
    return session.scalar(
        select(ReviewItemRow).where(
            ReviewItemRow.tenant_id == tenant_id,
            ReviewItemRow.id == item_id,
        )
    )
