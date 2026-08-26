from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..database import SessionLocal, set_public_tenant_context
from ..model_mixins import utcnow
from ..repositories import search_analytics_repository as repository


logger = logging.getLogger(__name__)


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


def record_storefront_search_background(tenant_id: UUID, term: str) -> None:
    """Persist analytics outside the catalog response transaction.

    Search analytics must never make a public catalog request fail.  A short
    independent session also means the catalog endpoint can keep its read-only
    transaction and the aggregation write cannot be lost when that session is
    closed without a commit.
    """

    try:
        with SessionLocal() as session:
            set_public_tenant_context(session, tenant_id=tenant_id)
            if record_storefront_search(session, tenant_id=tenant_id, term=term):
                session.commit()
    except Exception:
        logger.warning(
            "storefront search analytics write failed for tenant %s",
            tenant_id,
            exc_info=True,
        )


def popular_search_window(*, days: int, now: datetime | None = None) -> tuple[date, date]:
    occurred_at = now or utcnow()
    end_date = occurred_at.date()
    return end_date - timedelta(days=days - 1), end_date
