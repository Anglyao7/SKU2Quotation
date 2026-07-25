from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import set_request_context
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
from .public_catalog_models import TenantPublicProfileRow
from .saas_seed import PERMISSION_SEEDS, ROLE_SEEDS
from .inventory_seed import ensure_default_warehouse
from .tenant_slugs import is_reserved_tenant_slug, storefront_slug_from_name


SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
ORG_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,49}$")
BOOTSTRAP_NAMESPACE = UUID("a578b8b2-7a37-4a9f-aab9-0eae3dc78979")


@dataclass(frozen=True, slots=True)
class ProductionBootstrapResult:
    organization_id: UUID
    tenant_id: UUID
    user_id: UUID
    membership_id: UUID
    pending_identity: bool


def _normalized_email(value: str) -> str:
    normalized = value.strip().lower()
    if (
        len(normalized) > 320
        or normalized.count("@") != 1
        or not all(normalized.split("@", 1))
        or any(char.isspace() for char in normalized)
    ):
        raise ValueError("owner email is invalid")
    return normalized


def bootstrap_production_owner(
    session: Session,
    *,
    organization_code: str,
    organization_name: str,
    tenant_slug: str,
    tenant_name: str,
    owner_email: str,
    owner_display_name: str,
    platform_admin: bool = False,
) -> ProductionBootstrapResult:
    """Idempotently create one production tenant and an OIDC-bound OWNER invite.

    This function never creates an active password/local identity. The owner
    remains invited under ``pending_oidc`` until a configured OIDC provider
    returns the exact email with ``email_verified=true``.
    """

    code = organization_code.strip().upper()
    identity_slug = tenant_slug.strip().lower()
    canonical_slug = storefront_slug_from_name(tenant_name)
    email = _normalized_email(owner_email)
    if not ORG_CODE_PATTERN.fullmatch(code):
        raise ValueError("organization code is invalid")
    if not SLUG_PATTERN.fullmatch(identity_slug):
        raise ValueError("tenant slug is invalid")
    if is_reserved_tenant_slug(identity_slug):
        raise ValueError("tenant slug is reserved by the platform")
    if not organization_name.strip() or len(organization_name.strip()) > 200:
        raise ValueError("organization name is invalid")
    if not tenant_name.strip() or len(tenant_name.strip()) > 200:
        raise ValueError("tenant name is invalid")
    if not owner_display_name.strip() or len(owner_display_name.strip()) > 120:
        raise ValueError("owner display name is invalid")

    # Stable IDs make the operation idempotent even for the migration/table
    # owner, which is NOBYPASSRLS and subject to FORCE RLS policies.
    organization_id = uuid5(BOOTSTRAP_NAMESPACE, f"organization:{code}")
    # Keep the configured bootstrap slug solely as a stable deployment
    # identity. The customer-facing path follows the editable merchant name.
    tenant_id = uuid5(BOOTSTRAP_NAMESPACE, f"tenant:{code}:{identity_slug}")
    user_id = uuid5(BOOTSTRAP_NAMESPACE, f"owner:{email}")
    membership_id = uuid5(
        BOOTSTRAP_NAMESPACE, f"membership:{tenant_id}:{user_id}"
    )
    set_request_context(
        session,
        organization_id=organization_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    organization = session.get(OrganizationRow, organization_id)
    if organization is None:
        organization = OrganizationRow(
            id=organization_id,
            code=code,
            name=organization_name.strip(),
            status="active",
        )
        session.add(organization)
        session.flush()
    elif organization.code != code:
        raise ValueError("bootstrap organization identity does not match")
    elif organization.status != "active":
        raise ValueError("existing organization is not active")

    tenant = session.get(TenantRow, tenant_id)
    if tenant is None:
        tenant = TenantRow(
            id=tenant_id,
            organization_id=organization.id,
            slug=canonical_slug,
            name=tenant_name.strip(),
            status="active",
        )
        session.add(tenant)
        session.flush()
    elif tenant.organization_id != organization.id:
        raise ValueError("bootstrap tenant identity does not match")
    elif tenant.status != "active":
        raise ValueError("existing tenant is not active")

    user = session.get(UserRow, user_id)
    if user is not None:
        if user.email_normalized != email:
            raise ValueError("bootstrap owner identity does not match")
        if user.status not in {"invited", "active"}:
            raise ValueError("existing owner identity is not eligible")
        if not (
            user.identity_provider == "pending_oidc"
            or user.identity_provider.startswith("oidc:")
        ):
            raise ValueError("existing owner uses an ineligible identity provider")
    else:
        user = UserRow(
            id=user_id,
            email_normalized=email,
            display_name=owner_display_name.strip(),
            identity_provider="pending_oidc",
            identity_subject=f"pending:{user_id}",
            status="invited",
            is_platform_admin=platform_admin,
        )
        session.add(user)
        session.flush()
    if platform_admin:
        user.is_platform_admin = True

    membership = session.get(MembershipRow, membership_id)
    if membership is None:
        membership = MembershipRow(
            id=membership_id,
            tenant_id=tenant.id,
            user_id=user.id,
            status="invited" if user.status == "invited" else "active",
            job_title="Owner",
        )
        session.add(membership)
    elif (
        membership.tenant_id != tenant.id
        or membership.user_id != user.id
        or membership.status not in {"invited", "active"}
    ):
        raise ValueError("existing owner membership is not eligible")

    permissions = {
        row.code: row for row in session.scalars(select(PermissionRow)).all()
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

    roles = {
        row.code: row
        for row in session.scalars(
            select(RoleRow).where(RoleRow.tenant_id == tenant.id)
        ).all()
    }
    for role_code in ROLE_SEEDS:
        if role_code not in roles:
            role = RoleRow(
                tenant_id=tenant.id,
                code=role_code,
                name=role_code.title(),
                is_system=True,
                status="active",
            )
            session.add(role)
            roles[role_code] = role
        elif roles[role_code].status != "active":
            raise ValueError(f"system role {role_code} is disabled")
    session.flush()

    existing_grants = {
        (row.role_id, row.permission_id)
        for row in session.scalars(
            select(RolePermissionRow).where(
                RolePermissionRow.tenant_id == tenant.id
            )
        ).all()
    }
    for role_code, permission_codes in ROLE_SEEDS.items():
        role = roles[role_code]
        for permission_code in permission_codes:
            permission = permissions[permission_code]
            if (role.id, permission.id) not in existing_grants:
                session.add(
                    RolePermissionRow(
                        tenant_id=tenant.id,
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )

    session.flush()
    owner_role = roles["OWNER"]
    assignment = session.scalar(
        select(MembershipRoleRow).where(
            MembershipRoleRow.tenant_id == tenant.id,
            MembershipRoleRow.membership_id == membership.id,
            MembershipRoleRow.role_id == owner_role.id,
        )
    )
    if assignment is None:
        session.add(
            MembershipRoleRow(
                tenant_id=tenant.id,
                membership_id=membership.id,
                role_id=owner_role.id,
                assigned_by_user_id=user.id,
            )
        )
    profile = session.get(TenantPublicProfileRow, tenant.id)
    if profile is None:
        session.add(
            TenantPublicProfileRow(
                tenant_id=tenant.id,
                slug=tenant.slug,
                contact_email=email,
                publication_status="PUBLISHED",
            )
        )
    ensure_default_warehouse(
        session,
        tenant_id=tenant.id,
        created_by_membership_id=membership.id,
    )
    session.commit()
    return ProductionBootstrapResult(
        organization_id=organization.id,
        tenant_id=tenant.id,
        user_id=user.id,
        membership_id=membership.id,
        pending_identity=user.identity_provider == "pending_oidc",
    )
