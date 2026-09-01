from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..model_mixins import utcnow
from ..repositories import search_analytics_repository as repository


def normalize_search_term(value: object) -> tuple[str, str] | None:
    """Collapse whitespace and case for stable, privacy-safe aggregation."""

    display = " ".join(str(value or "").split()).strip()[:200]
    if not display:
        return None
    return display.casefold(), display


def record_storefront_search(
    session: Session,
    *,
    tenant_id: UUID,
    term: str,
    now: datetime | None = None,
) -> bool:
    normalized = normalize_search_term(term)
    if normalized is None:
        return False
    term_normalized, term_display = normalized
    occurred_at = now or utcnow()
    repository.increment_search_term(
        session,
        tenant_id=tenant_id,
        searched_on=occurred_at.date(),
        term_normalized=term_normalized,
        term_display=term_display,
        occurred_at=occurred_at,
    )
    return True


def popular_search_window(*, days: int, now: datetime | None = None) -> tuple[date, date]:
    occurred_at = now or utcnow()
    end_date = occurred_at.date()
    return end_date - timedelta(days=days - 1), end_date
