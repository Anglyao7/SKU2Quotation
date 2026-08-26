from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..search_analytics_models import StorefrontSearchTermDailyRow


def increment_search_term(
    session: Session,
    *,
    tenant_id: UUID,
    searched_on: date,
    term_normalized: str,
    term_display: str,
    occurred_at: datetime,
) -> None:
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "searched_on": searched_on,
        "term_normalized": term_normalized,
        "term_display": term_display,
        "search_count": 1,
        "last_searched_at": occurred_at,
        "created_at": occurred_at,
        "updated_at": occurred_at,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(StorefrontSearchTermDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_storefront_search_term_daily_term",
                set_={
                    "search_count": StorefrontSearchTermDailyRow.search_count + 1,
                    "last_searched_at": occurred_at,
                    "updated_at": occurred_at,
                    "deleted_at": None,
                },
            )
        )
        return
    if dialect == "sqlite":
        statement = sqlite_insert(StorefrontSearchTermDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "searched_on", "term_normalized"],
                set_={
                    "search_count": StorefrontSearchTermDailyRow.search_count + 1,
                    "last_searched_at": occurred_at,
                    "updated_at": occurred_at,
                    "deleted_at": None,
                },
            )
        )
        return

    existing = session.scalar(
        select(StorefrontSearchTermDailyRow).where(
            StorefrontSearchTermDailyRow.tenant_id == tenant_id,
            StorefrontSearchTermDailyRow.searched_on == searched_on,
            StorefrontSearchTermDailyRow.term_normalized == term_normalized,
        )
    )
    if existing is None:
        session.add(StorefrontSearchTermDailyRow(**values))
        return
    existing.search_count += 1
    existing.last_searched_at = occurred_at
    existing.updated_at = occurred_at
    existing.deleted_at = None


def list_popular_search_terms(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    limit: int,
) -> list[dict[str, object]]:
    statement = (
        select(
            StorefrontSearchTermDailyRow.term_normalized,
            func.max(StorefrontSearchTermDailyRow.term_display).label("term_display"),
            func.sum(StorefrontSearchTermDailyRow.search_count).label("search_count"),
            func.max(StorefrontSearchTermDailyRow.last_searched_at).label(
                "last_searched_at"
            ),
        )
        .where(
            StorefrontSearchTermDailyRow.tenant_id == tenant_id,
            StorefrontSearchTermDailyRow.searched_on >= start_date,
            StorefrontSearchTermDailyRow.searched_on <= end_date,
            StorefrontSearchTermDailyRow.deleted_at.is_(None),
        )
        .group_by(StorefrontSearchTermDailyRow.term_normalized)
        .order_by(
            func.sum(StorefrontSearchTermDailyRow.search_count).desc(),
            func.max(StorefrontSearchTermDailyRow.last_searched_at).desc(),
            StorefrontSearchTermDailyRow.term_normalized.asc(),
        )
        .limit(limit)
    )
    return [dict(row) for row in session.execute(statement).mappings().all()]
