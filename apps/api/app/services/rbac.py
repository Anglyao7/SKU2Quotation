from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..identity_models import (
    MembershipRoleRow,
    MembershipRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    TenantRow,
)
from ..tenant_modules import enabled_permission_modules


PLATFORM_ADMIN_ONLY_PERMISSION_CODES = frozenset(
    {
        "support.ai.manage",
        "support.ai.inspect",
        "support.ai.test",
        "knowledge.manage",
        "knowledge.approve",
    }
)


def list_permissions(session: Session, *, tenant_id: UUID, user_id: UUID) -> frozenset[str]:
    statement = (
        select(PermissionRow.code, PermissionRow.module)
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
    tenant_modules = session.scalar(
        select(TenantRow.enabled_modules).where(TenantRow.id == tenant_id)
    )
    allowed_permission_modules = enabled_permission_modules(tenant_modules)
    return frozenset(
        code
        for code, permission_module in session.execute(statement).all()
        if (
            permission_module in allowed_permission_modules
            and code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
        )
    )


def has_permission(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission_code: str,
) -> bool:
    return permission_code in list_permissions(session, tenant_id=tenant_id, user_id=user_id)
