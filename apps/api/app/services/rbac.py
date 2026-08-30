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


# A child account can browse the merchant's products, but it cannot mutate the
# merchant product library or publish the storefront catalog.  Keep the two
# read permissions explicit so a future product/catalog permission is denied
# by default instead of silently becoming available to every child account.
CUSTOMER_SUBACCOUNT_PRODUCT_READ_PERMISSION_CODES = frozenset(
    {
        "product.view",
        "catalog.view",
    }
)
CUSTOMER_SUBACCOUNT_PRODUCT_PERMISSION_MODULES = frozenset({"product", "catalog"})


# These owner-only records and actions must never be granted by the
# child-account role. Product selling prices are intentionally not listed:
# they are the child account's effective prices and are redacted separately by
# the product read use cases.
CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES = frozenset(
    {
        "product.create",
        "product.edit",
        "product.import",
        "product.review",
        "product.cost.read",
        "product.cost.write",
        "catalog.publish",
        "supplier.view",
        "supplier.manage",
        "system.user_manage",
        "system.role_manage",
        "system.settings_manage",
        "customer_portal.subaccount_manage",
        # Children may reply to conversations when the support module is
        # enabled, but storefront floating actions and welcome content belong
        # exclusively to the merchant account.
        "support.settings_manage",
        # These modules aggregate the merchant workspace rather than a
        # child account's own queue. A reseller may still browse products and
        # operate its own quote workflow, but must not infer the owner's
        # traffic, stock, or warehouse activity from a shared tenant report.
        "analytics.view",
        "inventory.view",
        "inventory.adjust",
        "inventory.purchase",
        "inventory.sale",
        "inventory.transfer",
        "inventory.warehouse_manage",
    }
)


PLATFORM_ADMIN_ONLY_PERMISSION_CODES = frozenset(
    {
        "support.ai.manage",
        "support.ai.inspect",
        "support.ai.test",
        "knowledge.manage",
        "knowledge.approve",
    }
)


def _customer_subaccount_permission_is_allowed(code: str, module: str) -> bool:
    if module in CUSTOMER_SUBACCOUNT_PRODUCT_PERMISSION_MODULES:
        return code in CUSTOMER_SUBACCOUNT_PRODUCT_READ_PERMISSION_CODES
    return (
        code not in CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES
        and code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
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
    membership_row = session.scalar(
        select(MembershipRow).where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.user_id == user_id,
            MembershipRow.status == "active",
            MembershipRow.deleted_at.is_(None),
        )
    )
    account_overrides = (
        membership_row.permission_overrides if membership_row is not None else None
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
    is_customer_subaccount = (
        membership_row is not None
        and membership_row.account_scope == "CUSTOMER_SUBACCOUNT"
    )
    resolved = {
        code
        for code, permission_module in session.execute(statement).all()
        if (
            permission_module in allowed_permission_modules
            and code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
            and (
                not is_customer_subaccount
                or _customer_subaccount_permission_is_allowed(
                    code,
                    permission_module,
                )
            )
            and (
                account_permission_ceiling is None
                or code in account_permission_ceiling
            )
        )
    }

    # Existing child accounts were created with the old three-item customer
    # portal role.  Expand that legacy role into a normal operator workspace
    # at read time so they do not need to be recreated, while preserving the
    # explicit owner-only exclusions above.  Tenant module ceilings still
    # apply, and a future expanded permission override remains authoritative.
    if (
        membership_row is not None
        and membership_row.account_scope == "CUSTOMER_SUBACCOUNT"
        and (
            account_permission_ceiling is None
            or account_permission_ceiling
            == {
                "customer_portal.access",
                "customer_portal.order_create",
                "customer_portal.order_view_self",
            }
        )
    ):
        available = session.execute(
            select(PermissionRow.code, PermissionRow.module).where(
                PermissionRow.deleted_at.is_(None)
            )
        ).all()
        resolved.update(
            code
            for code, permission_module in available
            if permission_module in allowed_permission_modules
            and _customer_subaccount_permission_is_allowed(code, permission_module)
        )

    # Newer child accounts store a concrete, parent-selected permission
    # ceiling instead of relying on the legacy portal role.  The role still
    # anchors the account to the child scope, while this expansion makes the
    # selected ordinary workspace actions available without granting the
    # owner-only modules listed above.
    elif (
        membership_row is not None
        and membership_row.account_scope == "CUSTOMER_SUBACCOUNT"
        and account_permission_ceiling is not None
    ):
        available = session.execute(
            select(PermissionRow.code, PermissionRow.module).where(
                PermissionRow.deleted_at.is_(None)
            )
        ).all()
        resolved.update(
            code
            for code, permission_module in available
            if code in account_permission_ceiling
            and permission_module in allowed_permission_modules
            and _customer_subaccount_permission_is_allowed(code, permission_module)
        )

    # Enforce the boundary even if a legacy role or a hand-edited permission
    # override accidentally contains an owner-only code.  The parent can
    # still decide which ordinary workspace modules the child uses, but these
    # codes are never valid for a customer subaccount.
    if membership_row is not None and membership_row.account_scope == "CUSTOMER_SUBACCOUNT":
        resolved.difference_update(CUSTOMER_SUBACCOUNT_SENSITIVE_PERMISSION_CODES)
    return frozenset(resolved)


def has_permission(
    session: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    permission_code: str,
) -> bool:
    return permission_code in list_permissions(session, tenant_id=tenant_id, user_id=user_id)
