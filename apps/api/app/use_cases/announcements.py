from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from ..announcement_models import StorefrontAnnouncementRow
from ..announcement_schemas import (
    AnnouncementListResponse,
    AnnouncementResponse,
    AnnouncementWriteRequest,
    PublicAnnouncementResponse,
)
from ..domain.errors import ApplicationError
from ..model_mixins import mark_deleted, utcnow
from ..repositories import announcement_repository as repository


def _require_manage(permissions: frozenset[str]) -> None:
    if "announcement.manage" not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            "Permission is required: announcement.manage",
            kind="forbidden",
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _schedule(request: AnnouncementWriteRequest) -> tuple[datetime, datetime]:
    starts_at = _utc(request.starts_at)
    ends_at = (
        _utc(request.ends_at)
        if request.ends_at is not None
        else starts_at + timedelta(days=int(request.duration_days or 0))
    )
    if ends_at <= starts_at:
        raise ApplicationError(
            "ANNOUNCEMENT_SCHEDULE_INVALID",
            "Announcement end time must be later than its start time.",
            kind="validation",
        )
    return starts_at, ends_at


def _response(
    row: StorefrontAnnouncementRow,
    *,
    now: datetime | None = None,
) -> AnnouncementResponse:
    timestamp = now or utcnow()
    return AnnouncementResponse(
        id=row.id,
        title=row.title,
        display_type=row.display_type,
        ticker_text=row.ticker_text,
        content_blocks=row.content_blocks or [],
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        repeat_interval_hours=row.repeat_interval_hours,
        publication_status=row.publication_status,
        version=row.version,
        is_active=(
            row.publication_status == "PUBLISHED"
            and _utc(row.starts_at) <= timestamp < _utc(row.ends_at)
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_announcements(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> AnnouncementListResponse:
    _require_manage(permissions)
    rows, total = repository.list_for_tenant(session, tenant_id=tenant_id)
    now = utcnow()
    return AnnouncementListResponse(
        items=[_response(row, now=now) for row in rows],
        total=total,
    )


def create_announcement(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    request: AnnouncementWriteRequest,
) -> AnnouncementResponse:
    _require_manage(permissions)
    starts_at, ends_at = _schedule(request)
    row = StorefrontAnnouncementRow(
        tenant_id=tenant_id,
        title=request.title,
        display_type=request.display_type,
        ticker_text=request.ticker_text if request.display_type == "TICKER" else None,
        content_blocks=(
            [block.model_dump(exclude_none=True) for block in request.content_blocks]
            if request.display_type == "MODAL"
            else []
        ),
        starts_at=starts_at,
        ends_at=ends_at,
        repeat_interval_hours=request.repeat_interval_hours,
        publication_status=request.publication_status,
        version=1,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _response(row)


def update_announcement(
    session: Session,
    *,
    tenant_id: UUID,
    announcement_id: UUID,
    user_id: UUID,
    permissions: frozenset[str],
    request: AnnouncementWriteRequest,
) -> AnnouncementResponse:
    _require_manage(permissions)
    row = repository.get_for_tenant(
        session,
        tenant_id=tenant_id,
        announcement_id=announcement_id,
    )
    if row is None:
        raise ApplicationError(
            "ANNOUNCEMENT_NOT_FOUND",
            "Announcement was not found.",
            kind="not_found",
        )
    starts_at, ends_at = _schedule(request)
    row.title = request.title
    row.display_type = request.display_type
    row.ticker_text = request.ticker_text if request.display_type == "TICKER" else None
    row.content_blocks = (
        [block.model_dump(exclude_none=True) for block in request.content_blocks]
        if request.display_type == "MODAL"
        else []
    )
    row.starts_at = starts_at
    row.ends_at = ends_at
    row.repeat_interval_hours = request.repeat_interval_hours
    row.publication_status = request.publication_status
    row.version += 1
    row.updated_by_user_id = user_id
    session.commit()
    session.refresh(row)
    return _response(row)


def delete_announcement(
    session: Session,
    *,
    tenant_id: UUID,
    announcement_id: UUID,
    permissions: frozenset[str],
) -> None:
    _require_manage(permissions)
    row = repository.get_for_tenant(
        session,
        tenant_id=tenant_id,
        announcement_id=announcement_id,
    )
    if row is None:
        raise ApplicationError(
            "ANNOUNCEMENT_NOT_FOUND",
            "Announcement was not found.",
            kind="not_found",
        )
    mark_deleted(row)
    session.commit()


def public_announcements(
    session: Session,
    *,
    tenant_id: UUID,
) -> list[PublicAnnouncementResponse]:
    return [
        PublicAnnouncementResponse(
            id=row.id,
            title=row.title,
            display_type=row.display_type,
            ticker_text=row.ticker_text,
            content_blocks=row.content_blocks or [],
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            repeat_interval_hours=row.repeat_interval_hours,
            version=row.version,
        )
        for row in repository.list_active(
            session,
            tenant_id=tenant_id,
            now=utcnow(),
        )
    ]
