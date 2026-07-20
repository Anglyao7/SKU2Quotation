from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from ..identity_models import MembershipRow, TenantRow


def get_membership(session: Session, membership_id: UUID) -> MembershipRow | None:
    return session.get(MembershipRow, membership_id)


def get_tenant(session: Session, tenant_id: UUID) -> TenantRow | None:
    return session.get(TenantRow, tenant_id)
