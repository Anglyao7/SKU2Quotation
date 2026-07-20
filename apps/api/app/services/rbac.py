from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..identity_models import (
    MembershipRoleRow,
    MembershipRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
)


def list_permissions(session: Session, *, tenant_id: UUID, user_id: UUID) -> frozenset[str]:
    statement = (
        select(PermissionRow.code)
        .join(RolePermissionRow, RolePermissionRow.permission_id == PermissionRow.id)
        .join(RoleRow, RoleRow.id == RolePermissionRow.role_id)
        .join(MembershipRoleRow, MembershipRoleRow.role_id == RoleRow.id)
        .join(MembershipRow, MembershipRow.id == MembershipRoleRow.membership_id)
        .where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.user_id == user_id,
            MembershipRow.status == "active",
            RoleRow.tenant_id == tenant_id,
            RoleRow.status == "active",
            RolePermissionRow.tenant_id == tenant_id,
            MembershipRoleRow.tenant_id == tenant_id,
            MembershipRow.deleted_at.is_(None),
            RoleRow.deleted_at.is_(None),
            PermissionRow.deleted_at.is_(None),
            RolePermissionRow.deleted_at.is_(None),
            MembershipRoleRow.deleted_at.is_(None),
        )
        .distinct()
    )
    return frozenset(session.scalars(statement).all())


def has_permission(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission_code: str,
) -> bool:
    return permission_code in list_permissions(session, tenant_id=tenant_id, user_id=user_id)
