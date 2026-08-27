from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ..identity_models import (
    CustomerAccountAccessEventRow,
    MembershipRoleRow,
    MembershipRow,
    RoleRow,
    TenantRow,
    TenantSubscriptionRow,
    UserRow,
)
from ..platform_usage_models import StorefrontVisitEventRow
from ..product_center_models import SkuRow
from ..public_catalog_models import PublicQuoteDraftRow, TenantPublicProfileRow
from ..storefront_analytics_models import StorefrontProductViewDailyRow


def list_tenants(session: Session) -> list[TenantRow]:
    return list(session.scalars(select(TenantRow).order_by(TenantRow.created_at, TenantRow.id)).all())


def get_tenant(session: Session, tenant_id: UUID) -> TenantRow | None:
    return session.get(TenantRow, tenant_id)


def get_tenant_subscription(
    session: Session,
    tenant_id: UUID,
) -> TenantSubscriptionRow | None:
    return session.get(TenantSubscriptionRow, tenant_id)


def get_public_profile(session: Session, tenant_id: UUID) -> TenantPublicProfileRow | None:
    return session.get(TenantPublicProfileRow, tenant_id)


def tenant_counts(session: Session, tenant_id: UUID) -> tuple[int, int]:
    sku_count = session.scalar(
        select(func.count(SkuRow.id)).where(
            SkuRow.tenant_id == tenant_id,
            SkuRow.deleted_at.is_(None),
        )
    )
    quote_count = session.scalar(
        select(func.count(PublicQuoteDraftRow.id)).where(PublicQuoteDraftRow.tenant_id == tenant_id)
    )
    return int(sku_count or 0), int(quote_count or 0)


def get_tenant_owner_account(
    session: Session,
    tenant_id: UUID,
) -> tuple[MembershipRow, UserRow] | None:
    """Return the oldest assigned OWNER account for the merchant, if any."""

    return session.execute(
        select(MembershipRow, UserRow)
        .join(UserRow, UserRow.id == MembershipRow.user_id)
        .join(
            MembershipRoleRow,
            (MembershipRoleRow.tenant_id == MembershipRow.tenant_id)
            & (MembershipRoleRow.membership_id == MembershipRow.id),
        )
        .join(
            RoleRow,
            (RoleRow.tenant_id == MembershipRoleRow.tenant_id)
            & (RoleRow.id == MembershipRoleRow.role_id),
        )
        .where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.account_scope == "STAFF",
            MembershipRow.status != "removed",
            RoleRow.code == "OWNER",
        )
        .order_by(MembershipRow.created_at, MembershipRow.id)
    ).first()


def list_tenant_subaccounts(
    session: Session,
    tenant_id: UUID,
) -> list[tuple[MembershipRow, UserRow]]:
    return list(
        session.execute(
            select(MembershipRow, UserRow)
            .join(UserRow, UserRow.id == MembershipRow.user_id)
            .where(
                MembershipRow.tenant_id == tenant_id,
                MembershipRow.account_scope == "CUSTOMER_SUBACCOUNT",
                MembershipRow.status.in_(("invited", "active", "suspended")),
                MembershipRow.deleted_at.is_(None),
                UserRow.deleted_at.is_(None),
            )
            .order_by(MembershipRow.created_at.desc(), MembershipRow.id)
        ).all()
    )


def membership_display_names(
    session: Session,
    *,
    tenant_id: UUID,
    membership_ids: list[UUID],
) -> dict[UUID, str]:
    if not membership_ids:
        return {}
    return {
        membership_id: display_name
        for membership_id, display_name in session.execute(
            select(MembershipRow.id, UserRow.display_name)
            .join(UserRow, UserRow.id == MembershipRow.user_id)
            .where(
                MembershipRow.tenant_id == tenant_id,
                MembershipRow.id.in_(membership_ids),
                MembershipRow.deleted_at.is_(None),
                UserRow.deleted_at.is_(None),
            )
        ).all()
    }


def subaccount_activity_metrics(
    session: Session,
    *,
    tenant_id: UUID,
    membership_ids: list[UUID],
    started_at: datetime,
) -> tuple[
    dict[UUID, tuple[int, datetime | None]],
    dict[UUID, tuple[int, datetime | None]],
]:
    if not membership_ids:
        return {}, {}
    access = {
        membership_id: (int(login_count or 0), last_login_at)
        for membership_id, login_count, last_login_at in session.execute(
            select(
                CustomerAccountAccessEventRow.membership_id,
                func.count(CustomerAccountAccessEventRow.id),
                func.max(CustomerAccountAccessEventRow.occurred_at),
            )
            .where(
                CustomerAccountAccessEventRow.tenant_id == tenant_id,
                CustomerAccountAccessEventRow.membership_id.in_(membership_ids),
                CustomerAccountAccessEventRow.event_type == "LOGIN",
                CustomerAccountAccessEventRow.occurred_at >= started_at,
            )
            .group_by(CustomerAccountAccessEventRow.membership_id)
        ).all()
    }
    quotes = {
        membership_id: (int(quote_count or 0), last_quote_at)
        for membership_id, quote_count, last_quote_at in session.execute(
            select(
                PublicQuoteDraftRow.submitted_by_membership_id,
                func.count(PublicQuoteDraftRow.id),
                func.max(PublicQuoteDraftRow.created_at),
            )
            .where(
                PublicQuoteDraftRow.tenant_id == tenant_id,
                PublicQuoteDraftRow.submitted_by_membership_id.in_(membership_ids),
            )
            .group_by(PublicQuoteDraftRow.submitted_by_membership_id)
        ).all()
    }
    return access, quotes


def quote_status_counts(
    session: Session,
    tenant_id: UUID,
) -> dict[str, int]:
    return {
        str(status): int(count or 0)
        for status, count in session.execute(
            select(PublicQuoteDraftRow.status, func.count(PublicQuoteDraftRow.id))
            .where(PublicQuoteDraftRow.tenant_id == tenant_id)
            .group_by(PublicQuoteDraftRow.status)
        ).all()
    }


def quote_dates_since(
    session: Session,
    *,
    tenant_id: UUID,
    started_at: datetime,
) -> list[datetime]:
    return list(
        session.scalars(
            select(PublicQuoteDraftRow.created_at).where(
                PublicQuoteDraftRow.tenant_id == tenant_id,
                PublicQuoteDraftRow.created_at >= started_at,
            )
        ).all()
    )


def last_quote_at(session: Session, tenant_id: UUID) -> datetime | None:
    return session.scalar(
        select(func.max(PublicQuoteDraftRow.created_at)).where(
            PublicQuoteDraftRow.tenant_id == tenant_id
        )
    )


def storefront_visitor_count(
    session: Session,
    *,
    tenant_id: UUID,
    started_at: datetime,
    ended_at: datetime,
) -> int:
    return int(
        session.scalar(
            select(func.count(distinct(StorefrontVisitEventRow.visitor_key))).where(
                StorefrontVisitEventRow.tenant_id == tenant_id,
                StorefrontVisitEventRow.occurred_at >= started_at,
                StorefrontVisitEventRow.occurred_at < ended_at,
            )
        )
        or 0
    )


def product_view_daily(
    session: Session,
    *,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
) -> dict[date, int]:
    return {
        viewed_on: int(view_count or 0)
        for viewed_on, view_count in session.execute(
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
    }


def list_recent_subaccount_quotes(
    session: Session,
    *,
    tenant_id: UUID,
    membership_id: UUID,
    limit: int = 20,
) -> list[PublicQuoteDraftRow]:
    return list(
        session.scalars(
            select(PublicQuoteDraftRow)
            .where(
                PublicQuoteDraftRow.tenant_id == tenant_id,
                PublicQuoteDraftRow.submitted_by_membership_id == membership_id,
            )
            .order_by(PublicQuoteDraftRow.created_at.desc(), PublicQuoteDraftRow.id)
            .limit(limit)
        ).all()
    )
