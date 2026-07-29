from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..announcement_models import StorefrontAnnouncementRow


def list_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
) -> tuple[list[StorefrontAnnouncementRow], int]:
    predicate = StorefrontAnnouncementRow.tenant_id == tenant_id
    total = int(
        session.scalar(
            select(func.count(StorefrontAnnouncementRow.id)).where(predicate)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(StorefrontAnnouncementRow)
            .where(predicate)
            .order_by(
                StorefrontAnnouncementRow.starts_at.desc(),
                StorefrontAnnouncementRow.created_at.desc(),
            )
        ).all()
    )
    return rows, total


def get_for_tenant(
    session: Session,
    *,
    tenant_id: UUID,
    announcement_id: UUID,
) -> StorefrontAnnouncementRow | None:
    return session.scalar(
        select(StorefrontAnnouncementRow).where(
            StorefrontAnnouncementRow.tenant_id == tenant_id,
            StorefrontAnnouncementRow.id == announcement_id,
        )
    )


def list_active(
    session: Session,
    *,
    tenant_id: UUID,
    now: datetime,
) -> list[StorefrontAnnouncementRow]:
    return list(
        session.scalars(
            select(StorefrontAnnouncementRow)
            .where(
                StorefrontAnnouncementRow.tenant_id == tenant_id,
                StorefrontAnnouncementRow.publication_status == "PUBLISHED",
                StorefrontAnnouncementRow.starts_at <= now,
                StorefrontAnnouncementRow.ends_at > now,
            )
            .order_by(
                StorefrontAnnouncementRow.starts_at.desc(),
                StorefrontAnnouncementRow.created_at.desc(),
            )
        ).all()
    )
