import os
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import DATABASE_URL, set_request_context
from .constants import (
    DEFAULT_MEMBERSHIP_ID,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_OWNER_USER_ID,
    DEFAULT_TENANT_ID,
)
from .identity_models import (
    MembershipRoleRow,
    MembershipRow,
    OrganizationRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    TenantRow,
    UserRow,
)
from .model_mixins import restore_deleted
from .inventory_seed import ensure_default_warehouse


@dataclass(frozen=True)
class PermissionSeed:
    code: str
    module: str
    action: str
    description: str


PERMISSION_SEEDS = (
    PermissionSeed("product.view", "product", "view", "View products"),
    PermissionSeed("product.create", "product", "create", "Create products"),
    PermissionSeed("product.edit", "product", "edit", "Edit products"),
    PermissionSeed("product.import", "product", "import", "Import the fixed product workbook"),
    PermissionSeed("product.review", "product", "review", "Review and adopt product candidates"),
    PermissionSeed("product.cost.read", "product", "cost_read", "View supplier cost history"),
    PermissionSeed("product.cost.write", "product", "cost_write", "Create supplier cost records"),
    PermissionSeed("supplier.view", "supplier", "view", "View suppliers"),
    PermissionSeed("supplier.manage", "supplier", "manage", "Manage suppliers"),
    PermissionSeed("customer.view", "customer", "view", "View customers"),
    PermissionSeed("customer.manage", "customer", "manage", "Manage customers"),
    PermissionSeed("inquiry.view", "inquiry", "view", "View inquiries"),
    PermissionSeed("inquiry.manage", "inquiry", "manage", "Manage inquiries"),
    PermissionSeed("quotation.view", "quotation", "view", "View quotations"),
    PermissionSeed("quotation.create", "quotation", "create", "Create quotations"),
    PermissionSeed("quotation.approve", "quotation", "approve", "Approve quotations"),
    PermissionSeed("catalog.view", "catalog", "view", "View catalogs"),
    PermissionSeed("catalog.publish", "catalog", "publish", "Publish catalogs"),
    PermissionSeed(
        "analytics.view",
        "analytics",
        "view",
        "View tenant storefront product analytics",
    ),
    PermissionSeed(
        "announcement.manage",
        "announcement",
        "manage",
        "Create, schedule, publish, and remove storefront announcements",
    ),
    PermissionSeed(
        "support.view",
        "support",
        "view",
        "View storefront customer-service conversations",
    ),
    PermissionSeed(
        "support.reply",
        "support",
        "reply",
        "Reply to and close storefront customer-service conversations",
    ),
    PermissionSeed(
        "support.settings_manage",
        "support",
        "settings_manage",
        "Manage storefront support floating actions and welcome content",
    ),
    PermissionSeed(
        "support.ai.manage",
        "support_ai",
        "manage",
        "Manage customer-service AI policy and automation mode",
    ),
    PermissionSeed(
        "support.ai.inspect",
        "support_ai",
        "inspect",
        "Inspect customer-service AI runs, evidence, and decisions",
    ),
    PermissionSeed(
        "support.ai.test",
        "support_ai",
        "test",
        "Run customer-service AI test-lab questions",
    ),
    PermissionSeed(
        "knowledge.manage",
        "knowledge",
        "manage",
        "Upload, reindex, and revoke customer-facing knowledge sources",
    ),
    PermissionSeed(
        "knowledge.approve",
        "knowledge",
        "approve",
        "Approve customer-facing knowledge sources for AI use",
    ),
    PermissionSeed("order.view", "order", "view", "View orders"),
    PermissionSeed("order.manage", "order", "manage", "Manage orders"),
    PermissionSeed("inventory.view", "inventory", "view", "View inventory and stock movements"),
    PermissionSeed("inventory.adjust", "inventory", "adjust", "Post inventory adjustments"),
    PermissionSeed("inventory.purchase", "inventory", "purchase", "Manage purchase orders and receipts"),
    PermissionSeed("inventory.sale", "inventory", "sale", "Manage sales orders and shipments"),
    PermissionSeed("inventory.transfer", "inventory", "transfer", "Transfer stock between warehouses"),
    PermissionSeed(
        "inventory.warehouse_manage",
        "inventory",
        "warehouse_manage",
        "Manage warehouses",
    ),
    PermissionSeed("system.user_manage", "system", "user_manage", "Manage tenant members"),
    PermissionSeed("system.role_manage", "system", "role_manage", "Manage tenant roles"),
    PermissionSeed("system.settings_manage", "system", "settings_manage", "Manage tenant settings"),
    PermissionSeed(
        "customer_portal.subaccount_manage",
        "customer_portal",
        "subaccount_manage",
        "Create, suspend, and review customer subaccounts",
    ),
    PermissionSeed(
        "customer_portal.access",
        "customer_portal",
        "access",
        "Access the customer ordering portal",
    ),
    PermissionSeed(
        "customer_portal.order_create",
        "customer_portal",
        "order_create",
        "Create a customer order request from the catalog",
    ),
    PermissionSeed(
        "customer_portal.order_view_self",
        "customer_portal",
        "order_view_self",
        "View own customer order requests",
    ),
)

ROLE_SEEDS = {
    "OWNER": {seed.code for seed in PERMISSION_SEEDS},
    "ADMIN": {seed.code for seed in PERMISSION_SEEDS},
    "SALES": {
        "product.view", "product.import", "supplier.view", "customer.view", "customer.manage",
        "inquiry.view", "inquiry.manage", "quotation.view", "quotation.create",
        "catalog.view", "catalog.publish", "announcement.manage", "order.view",
        "inventory.view", "inventory.sale", "support.view", "support.reply",
        "support.ai.inspect",
    },
    "PURCHASING": {
        "product.view", "product.create", "product.edit", "product.import", "product.review",
        "product.cost.read", "product.cost.write",
        "supplier.view", "supplier.manage", "inquiry.view", "quotation.view",
        "order.view", "order.manage",
        "inventory.view", "inventory.adjust", "inventory.purchase", "inventory.transfer",
    },
    # Read-only tenant member. SALES and PURCHASING remain the two scoped
    # editor variants so existing merchant assignments stay backward compatible.
    "VIEWER": {
        "product.view", "supplier.view", "customer.view", "inquiry.view",
        "quotation.view", "catalog.view", "order.view", "inventory.view",
    },
    "CUSTOMER_SUBACCOUNT": {
        "customer_portal.access",
        "customer_portal.order_create",
        "customer_portal.order_view_self",
    },
}


def ensure_tenant_rbac(session: Session, *, tenant_id: UUID) -> dict[str, RoleRow]:
    """Idempotently provision the immutable system-role catalogue for one tenant.

    The caller must already have bound the target tenant RLS context.  The
    function deliberately does not commit so it can participate in tenant
    creation and other administrative transactions.
    """

    permissions = {
        permission.code: permission
        for permission in session.scalars(
            select(PermissionRow).execution_options(include_deleted=True)
        ).all()
    }
    for seed in PERMISSION_SEEDS:
        if seed.code not in permissions:
            permission = PermissionRow(
                code=seed.code,
                module=seed.module,
                action=seed.action,
                description=seed.description,
            )
            session.add(permission)
            permissions[seed.code] = permission
        elif permissions[seed.code].deleted_at is not None:
            restore_deleted(permissions[seed.code])
        permission = permissions[seed.code]
        permission.module = seed.module
        permission.action = seed.action
        permission.description = seed.description

    roles = {
        role.code: role
        for role in session.scalars(
            select(RoleRow)
            .where(RoleRow.tenant_id == tenant_id)
            .execution_options(include_deleted=True)
        ).all()
    }
    for code in ROLE_SEEDS:
        if code not in roles:
            role = RoleRow(
                tenant_id=tenant_id,
                code=code,
                name=code.title(),
                is_system=True,
                status="active",
            )
            session.add(role)
            roles[code] = role
        elif roles[code].deleted_at is not None:
            restore_deleted(roles[code])
            roles[code].status = "active"

    session.flush()
    existing_role_permissions = {
        (row.role_id, row.permission_id): row
        for row in session.scalars(
            select(RolePermissionRow)
            .where(RolePermissionRow.tenant_id == tenant_id)
            .execution_options(include_deleted=True)
        ).all()
    }
    for role_code, permission_codes in ROLE_SEEDS.items():
        role = roles[role_code]
        for permission_code in permission_codes:
            permission = permissions[permission_code]
            key = (role.id, permission.id)
            if key not in existing_role_permissions:
                session.add(
                    RolePermissionRow(
                        tenant_id=tenant_id,
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
            elif existing_role_permissions[key].deleted_at is not None:
                restore_deleted(existing_role_permissions[key])
    session.flush()
    return roles


def demo_seed_enabled() -> bool:
    default = "true" if DATABASE_URL.startswith("sqlite") else "false"
    return os.getenv("SEED_DEMO_DATA", default).lower() in {"1", "true", "yes"}


def seed_saas_foundation(session: Session) -> None:
    """Idempotently seed one local tenant and the constitutional system roles."""
    set_request_context(
        session,
        organization_id=DEFAULT_ORGANIZATION_ID,
        tenant_id=DEFAULT_TENANT_ID,
        user_id=DEFAULT_OWNER_USER_ID,
    )

    include_deleted = {"include_deleted": True}
    organization = session.get(
        OrganizationRow, DEFAULT_ORGANIZATION_ID, execution_options=include_deleted
    )
    if organization is None:
        organization = OrganizationRow(
            id=DEFAULT_ORGANIZATION_ID, code="LOCAL", name="智贸云本地组织"
        )
        session.add(organization)
    elif organization.deleted_at is not None:
        restore_deleted(organization)
        organization.status = "active"

    tenant = session.get(TenantRow, DEFAULT_TENANT_ID, execution_options=include_deleted)
    if tenant is None:
        tenant = TenantRow(
            id=DEFAULT_TENANT_ID,
            organization_id=DEFAULT_ORGANIZATION_ID,
            slug="demo",
            name="Local Demo Company",
        )
        session.add(tenant)
    elif tenant.deleted_at is not None:
        restore_deleted(tenant)
        tenant.status = "active"
    # Keep the local demo URL stable across repeated seeds and upgrades from
    # the earlier internal-only `local` slug.
    if tenant.status == "active":
        tenant.slug = "demo"

    user = session.get(UserRow, DEFAULT_OWNER_USER_ID, execution_options=include_deleted)
    if user is None:
        user = UserRow(
            id=DEFAULT_OWNER_USER_ID,
            email_normalized="owner@local.aitradecloud.invalid",
            display_name="Local Owner",
            identity_provider="local-bootstrap",
            identity_subject=str(DEFAULT_OWNER_USER_ID),
            status="active",
        )
        session.add(user)
    elif user.deleted_at is not None:
        restore_deleted(user)
        user.status = "active"
    # The local-only demo identity doubles as the platform operator so the
    # integrated tenant-management flow can be exercised without external IdP setup.
    user.is_platform_admin = True

    session.flush()
    membership = session.get(
        MembershipRow, DEFAULT_MEMBERSHIP_ID, execution_options=include_deleted
    )
    if membership is None:
        membership = MembershipRow(
            id=DEFAULT_MEMBERSHIP_ID,
            tenant_id=DEFAULT_TENANT_ID,
            user_id=DEFAULT_OWNER_USER_ID,
            status="active",
        )
        session.add(membership)
    elif membership.deleted_at is not None:
        restore_deleted(membership)
        membership.status = "active"

    roles = ensure_tenant_rbac(session, tenant_id=DEFAULT_TENANT_ID)
    ensure_default_warehouse(
        session,
        tenant_id=DEFAULT_TENANT_ID,
        created_by_membership_id=DEFAULT_MEMBERSHIP_ID,
    )

    owner_role = roles["OWNER"]
    owner_assignment = session.scalar(
        select(MembershipRoleRow)
        .where(
            MembershipRoleRow.tenant_id == DEFAULT_TENANT_ID,
            MembershipRoleRow.membership_id == DEFAULT_MEMBERSHIP_ID,
            MembershipRoleRow.role_id == owner_role.id,
        )
        .execution_options(include_deleted=True)
    )
    if owner_assignment is None:
        session.add(MembershipRoleRow(
            tenant_id=DEFAULT_TENANT_ID,
            membership_id=DEFAULT_MEMBERSHIP_ID,
            role_id=owner_role.id,
            assigned_by_user_id=DEFAULT_OWNER_USER_ID,
        ))
    elif owner_assignment.deleted_at is not None:
        restore_deleted(owner_assignment)
    session.commit()
