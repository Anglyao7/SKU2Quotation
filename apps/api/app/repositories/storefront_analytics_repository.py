from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..storefront_analytics_models import (
    StorefrontProductViewDailyRow,
    StorefrontProductViewEventRow,
)


def event_exists(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: str,
) -> bool:
    return session.scalar(
        select(StorefrontProductViewEventRow.id).where(
            StorefrontProductViewEventRow.tenant_id == tenant_id,
            StorefrontProductViewEventRow.event_id == event_id,
        )
    ) is not None


def insert_event_if_absent(
    session: Session,
    *,
    tenant_id: UUID,
    event_id: str,
    product_id: UUID,
    sku_id: UUID,
    sku_code: str,
    product_name: str,
    ip_address: str,
    country_code: str,
    now: datetime,
) -> bool:
    """Insert the raw event once without leaving the aggregate transaction."""

    values = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "event_id": event_id,
        "product_id": product_id,
        "sku_id": sku_id,
        "sku_code_snapshot": sku_code,
        "product_name_snapshot": product_name,
        "ip_address": ip_address,
        "country_code": country_code,
        "occurred_at": now,
        "created_at": now,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            postgresql_insert(StorefrontProductViewEventRow)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_storefront_product_view_events_event"
            )
            .returning(StorefrontProductViewEventRow.id)
        )
        return session.scalar(statement) is not None
    if dialect == "sqlite":
        statement = (
            sqlite_insert(StorefrontProductViewEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "event_id"])
            .returning(StorefrontProductViewEventRow.id)
        )
        return session.scalar(statement) is not None

    if event_exists(session, tenant_id=tenant_id, event_id=event_id):
        return False
    session.add(StorefrontProductViewEventRow(**values))
    session.flush()
    return True


def increment_daily_view(
    session: Session,
    *,
    tenant_id: UUID,
    viewed_on: date,
    product_id: UUID,
    sku_id: UUID,
    sku_code: str,
    product_name: str,
    country_code: str,
    now: datetime,
) -> None:
    values = {
        "tenant_id": tenant_id,
        "viewed_on": viewed_on,
        "product_id": product_id,
        "sku_id": sku_id,
        "sku_code_snapshot": sku_code,
        "product_name_snapshot": product_name,
        "country_code": country_code,
        "view_count": 1,
        "created_at": now,
        "updated_at": now,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(StorefrontProductViewDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                constraint="uq_storefront_product_view_daily_bucket",
                set_={
                    "product_id": statement.excluded.product_id,
                    "sku_code_snapshot": statement.excluded.sku_code_snapshot,
                    "product_name_snapshot": statement.excluded.product_name_snapshot,
                    "view_count": StorefrontProductViewDailyRow.view_count + 1,
                    "updated_at": now,
                },
            )
        )
        return
    if dialect == "sqlite":
        statement = sqlite_insert(StorefrontProductViewDailyRow).values(**values)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["tenant_id", "viewed_on", "country_code", "sku_id"],
                set_={
                    "product_id": statement.excluded.product_id,
                    "sku_code_snapshot": statement.excluded.sku_code_snapshot,
                    "product_name_snapshot": statement.excluded.product_name_snapshot,
                    "view_count": StorefrontProductViewDailyRow.view_count + 1,
                    "updated_at": now,
                },
            )
        )
        return

    row = session.scalar(
        select(StorefrontProductViewDailyRow).where(
            StorefrontProductViewDailyRow.tenant_id == tenant_id,
            StorefrontProductViewDailyRow.viewed_on == viewed_on,
            StorefrontProductViewDailyRow.country_code == country_code,
            StorefrontProductViewDailyRow.sku_id == sku_id,
        )
    )
    if row is None:
        session.add(StorefrontProductViewDailyRow(**values))
        return
    row.product_id = product_id
    row.sku_code_snapshot = sku_code
    row.product_name_snapshot = product_name
    row.view_count += 1
    row.updated_at = now


def totals(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> tuple[int, int, int]:
    row = session.execute(
        select(
            func.coalesce(func.sum(StorefrontProductViewDailyRow.view_count), 0),
            func.count(distinct(StorefrontProductViewDailyRow.sku_id)),
            func.count(
                distinct(StorefrontProductViewDailyRow.country_code)
            ).filter(
                StorefrontProductViewDailyRow.country_code.not_in(
                    ("ZZ", "XX", "T1")
                )
            ),
        ).where(
            StorefrontProductViewDailyRow.tenant_id == tenant_id,
            StorefrontProductViewDailyRow.viewed_on >= start_date,
            StorefrontProductViewDailyRow.viewed_on <= end_date,
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


def unique_visitor_count(
    session: Session,
    *,
    tenant_id: UUID,
    started_at: datetime,
    ended_at: datetime,
) -> int:
    return int(
        session.scalar(
            select(func.count(distinct(StorefrontProductViewEventRow.ip_address))).where(
                StorefrontProductViewEventRow.tenant_id == tenant_id,
                StorefrontProductViewEventRow.occurred_at >= started_at,
                StorefrontProductViewEventRow.occurred_at < ended_at,
            )
        )
        or 0
    )


def daily_views(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> list[tuple[date, int]]:
    return [
        (row[0], int(row[1] or 0))
        for row in session.execute(
            select(
                StorefrontProductViewDailyRow.viewed_on,
                func.sum(StorefrontProductViewDailyRow.view_count),
            )
            .where(
                StorefrontProductViewDailyRow.tenant_id == tenant_id,
                StorefrontProductViewDailyRow.viewed_on >= start_date,
                StorefrontProductViewDailyRow.viewed_on <= end_date,
            )
            .group_by(StorefrontProductViewDailyRow.viewed_on)
            .order_by(StorefrontProductViewDailyRow.viewed_on)
        ).all()
    ]


def top_countries(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    limit: int,
) -> list[tuple[str, int]]:
    return [
        (str(row[0]), int(row[1] or 0))
        for row in session.execute(
            select(
                StorefrontProductViewDailyRow.country_code,
                func.sum(StorefrontProductViewDailyRow.view_count).label("views"),
            )
            .where(
                StorefrontProductViewDailyRow.tenant_id == tenant_id,
                StorefrontProductViewDailyRow.viewed_on >= start_date,
                StorefrontProductViewDailyRow.viewed_on <= end_date,
            )
            .group_by(StorefrontProductViewDailyRow.country_code)
            .order_by(func.sum(StorefrontProductViewDailyRow.view_count).desc())
            .limit(limit)
        ).all()
    ]


def top_products(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    limit: int,
) -> list[tuple[UUID, UUID, str, str, int]]:
    return [
        (row[0], row[1], str(row[2]), str(row[3]), int(row[4] or 0))
        for row in session.execute(
            select(
                StorefrontProductViewDailyRow.product_id,
                StorefrontProductViewDailyRow.sku_id,
                func.max(StorefrontProductViewDailyRow.sku_code_snapshot),
                func.max(StorefrontProductViewDailyRow.product_name_snapshot),
                func.sum(StorefrontProductViewDailyRow.view_count).label("views"),
            )
            .where(
                StorefrontProductViewDailyRow.tenant_id == tenant_id,
                StorefrontProductViewDailyRow.viewed_on >= start_date,
                StorefrontProductViewDailyRow.viewed_on <= end_date,
            )
            .group_by(
                StorefrontProductViewDailyRow.product_id,
                StorefrontProductViewDailyRow.sku_id,
            )
            .order_by(func.sum(StorefrontProductViewDailyRow.view_count).desc())
            .limit(limit)
        ).all()
    ]


def country_product_views(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    country_codes: list[str],
    sku_ids: list[UUID],
) -> list[tuple[str, UUID, int]]:
    if not country_codes or not sku_ids:
        return []
    return [
        (str(row[0]), row[1], int(row[2] or 0))
        for row in session.execute(
            select(
                StorefrontProductViewDailyRow.country_code,
                StorefrontProductViewDailyRow.sku_id,
                func.sum(StorefrontProductViewDailyRow.view_count),
            )
            .where(
                StorefrontProductViewDailyRow.tenant_id == tenant_id,
                StorefrontProductViewDailyRow.viewed_on >= start_date,
                StorefrontProductViewDailyRow.viewed_on <= end_date,
                StorefrontProductViewDailyRow.country_code.in_(country_codes),
                StorefrontProductViewDailyRow.sku_id.in_(sku_ids),
            )
            .group_by(
                StorefrontProductViewDailyRow.country_code,
                StorefrontProductViewDailyRow.sku_id,
            )
        ).all()
    ]


def delete_events_before(
    session: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
) -> int:
    result = session.execute(
        delete(StorefrontProductViewEventRow).where(
            StorefrontProductViewEventRow.tenant_id == tenant_id,
            StorefrontProductViewEventRow.occurred_at < cutoff,
        )
    )
    return int(result.rowcount or 0)
