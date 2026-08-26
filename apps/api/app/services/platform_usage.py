from __future__ import annotations

import hashlib
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..model_mixins import utcnow
from ..platform_usage_models import StorefrontVisitEventRow, TenantUsageDailyRow


def _visitor_key(ip_address: str) -> str:
    # A stable digest is enough for deduplication and avoids storing another
    # copy of the visitor's raw address in this new event stream.
    return hashlib.sha256(ip_address.strip().encode("utf-8")).hexdigest()


def record_storefront_visit(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: str,
    ip_address: str,
    country_code: str,
    now: datetime | None = None,
) -> bool:
    """Record one storefront visit without creating a per-page-view row."""

    occurred_at = now or utcnow()
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "event_id": event_id,
        "visitor_key": _visitor_key(ip_address),
        "country_code": (country_code or "ZZ").upper()[:2],
        "occurred_at": occurred_at,
        "created_at": occurred_at,
        "updated_at": occurred_at,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(StorefrontVisitEventRow)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_storefront_visit_events_event"
            )
            .returning(StorefrontVisitEventRow.id)
        )
        return session.scalar(statement) is not None
    if dialect == "sqlite":
        statement = (
            sqlite_insert(StorefrontVisitEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "event_id"])
            .returning(StorefrontVisitEventRow.id)
        )
        return session.scalar(statement) is not None

    existing = session.scalar(
        select(StorefrontVisitEventRow.id).where(
            StorefrontVisitEventRow.tenant_id == tenant_id,
            StorefrontVisitEventRow.event_id == event_id,
        )
    )
    if existing is not None:
        return False
    session.add(StorefrontVisitEventRow(**values))
    session.flush()
    return True


def increment_image_search(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime | None = None,
) -> None:
    """Increment the daily counter used for public and authenticated image search."""

    occurred_at = now or utcnow()
    usage_date: date = occurred_at.date()
    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "usage_date": usage_date,
        "image_search_count": 1,
        "created_at": occurred_at,
        "updated_at": occurred_at,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(TenantUsageDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_tenant_usage_daily_tenant_date",
                set_={
                    "image_search_count": TenantUsageDailyRow.image_search_count + 1,
                    "updated_at": occurred_at,
                },
            )
        )
        return
    if dialect == "sqlite":
        statement = sqlite_insert(TenantUsageDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "usage_date"],
                set_={
                    "image_search_count": TenantUsageDailyRow.image_search_count + 1,
                    "updated_at": occurred_at,
                },
            )
        )
        return

    row = session.scalar(
        select(TenantUsageDailyRow).where(
            TenantUsageDailyRow.tenant_id == tenant_id,
            TenantUsageDailyRow.usage_date == usage_date,
        )
    )
    if row is None:
        session.add(TenantUsageDailyRow(**values))
    else:
        row.image_search_count += 1
        row.updated_at = occurred_at
