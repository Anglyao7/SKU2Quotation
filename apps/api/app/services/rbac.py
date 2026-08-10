from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..identity_models import (
    MerchantIdentityProfileRow,
    MembershipRoleRow,
    MembershipRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    TenantRow,
)
from ..tenant_modules import effective_tenant_modules, enabled_permission_modules


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
    tenant_access = session.execute(
        select(
            TenantRow.identity_code,
            TenantRow.module_access_mode,
            TenantRow.enabled_modules,
        ).where(TenantRow.id == tenant_id)
    ).one_or_none()
    account_overrides = session.scalar(
        select(MembershipRow.permission_overrides).where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.user_id == user_id,
            MembershipRow.status == "active",
            MembershipRow.deleted_at.is_(None),
        )
    )
    account_permission_ceiling = (
        {str(code) for code in account_overrides}
        if isinstance(account_overrides, list)
        else None
    )
    identity_defaults = None
    if tenant_access is not None:
        identity_defaults = session.scalar(
            select(MerchantIdentityProfileRow.default_modules).where(
                MerchantIdentityProfileRow.code == tenant_access.identity_code,
                MerchantIdentityProfileRow.deleted_at.is_(None),
            )
        )
    tenant_modules = (
        effective_tenant_modules(
            identity_code=tenant_access.identity_code,
            access_mode=tenant_access.module_access_mode,
            custom_modules=tenant_access.enabled_modules,
            identity_default_modules=identity_defaults,
        )
        if tenant_access is not None
        else ()
    )
    allowed_permission_modules = enabled_permission_modules(tenant_modules)
    return frozenset(
        code
        for code, permission_module in session.execute(statement).all()
        if (
            permission_module in allowed_permission_modules
            and code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
            and (
                account_permission_ceiling is None
                or code in account_permission_ceiling
            )
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
