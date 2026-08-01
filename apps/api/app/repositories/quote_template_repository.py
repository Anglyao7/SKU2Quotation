from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..quote_template_models import QuoteExcelTemplateRow


def list_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[QuoteExcelTemplateRow]:
    return list(
        session.scalars(
            select(QuoteExcelTemplateRow)
            .where(QuoteExcelTemplateRow.tenant_id == tenant_id)
            .order_by(
                QuoteExcelTemplateRow.is_default.desc(),
                QuoteExcelTemplateRow.updated_at.desc(),
                QuoteExcelTemplateRow.id,
            )
        ).all()
    )


def get_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
    template_id: UUID,
) -> QuoteExcelTemplateRow | None:
    return session.scalar(
        select(QuoteExcelTemplateRow).where(
            QuoteExcelTemplateRow.tenant_id == tenant_id,
            QuoteExcelTemplateRow.id == template_id,
        )
    )


def get_default(
    session: Session,
    *,
    tenant_id: UUID,
) -> QuoteExcelTemplateRow | None:
    return session.scalar(
        select(QuoteExcelTemplateRow)
        .where(
            QuoteExcelTemplateRow.tenant_id == tenant_id,
            QuoteExcelTemplateRow.is_default.is_(True),
        )
        .order_by(QuoteExcelTemplateRow.updated_at.desc())
        .limit(1)
    )


def clear_default(
    session: Session,
    *,
    tenant_id: UUID,
    except_template_id: UUID | None = None,
) -> None:
    statement = (
        update(QuoteExcelTemplateRow)
        .where(
            QuoteExcelTemplateRow.tenant_id == tenant_id,
            QuoteExcelTemplateRow.is_default.is_(True),
        )
        .values(is_default=False)
    )
    if except_template_id is not None:
        statement = statement.where(QuoteExcelTemplateRow.id != except_template_id)
    session.execute(statement)
