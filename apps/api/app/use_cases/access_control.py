from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..access_control_schemas import (
    TenantMemberRoleSummary,
    TenantMemberRolesUpdateRequest,
    TenantMemberSummary,
    TenantPermissionSummary,
    TenantRoleCreateRequest,
    TenantRoleSummary,
    TenantRoleUpdateRequest,
)
from ..domain.errors import ApplicationError
from ..identity_models import MembershipRoleRow, PermissionRow, RolePermissionRow, RoleRow
from ..model_mixins import mark_deleted, restore_deleted, utcnow
from ..repositories import access_control_repository as repository
from ..services.rbac import PLATFORM_ADMIN_ONLY_PERMISSION_CODES


def _require(permissions: frozenset[str], code: str) -> None:
    if code not in permissions:
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"Permission is required: {code}",
            kind="forbidden",
        )


def _require_any(permissions: frozenset[str], *codes: str) -> None:
    if not permissions.intersection(codes):
        raise ApplicationError(
            "PERMISSION_DENIED",
            f"One of these permissions is required: {', '.join(codes)}",
            kind="forbidden",
        )


def _permission_rows_by_code(session: Session) -> dict[str, PermissionRow]:
    return {
        row.code: row
        for row in repository.list_permissions(session)
        if row.code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
    }


def _resolve_permission_rows(
    session: Session, permission_codes: list[str]
) -> list[PermissionRow]:
    by_code = _permission_rows_by_code(session)
    unknown = sorted(set(permission_codes) - set(by_code))
    if unknown:
        raise ApplicationError(
            "PERMISSION_CODE_INVALID",
            f"Unknown permission codes: {', '.join(unknown)}",
            kind="invalid",
        )
    return [by_code[code] for code in permission_codes]


def _require_delegable_permissions(
    actor_permissions: frozenset[str], requested_codes: set[str]
) -> None:
    excess = sorted(requested_codes - actor_permissions)
    if excess:
        raise ApplicationError(
            "PRIVILEGE_ESCALATION_FORBIDDEN",
            f"You cannot delegate permissions you do not hold: {', '.join(excess)}",
            kind="forbidden",
        )


def _permission_codes_by_role(
    session: Session, *, tenant_id: UUID, roles: list[RoleRow]
) -> dict[UUID, set[str]]:
    role_ids = [role.id for role in roles]
    permission_by_id = {
        row.id: row.code
        for row in repository.list_permissions(session)
        if row.code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
    }
    result = {role_id: set() for role_id in role_ids}
    for assignment in repository.role_permission_rows(
        session, tenant_id=tenant_id, role_ids=role_ids
    ):
        if assignment.deleted_at is None and assignment.permission_id in permission_by_id:
            result.setdefault(assignment.role_id, set()).add(
                permission_by_id[assignment.permission_id]
            )
    return result


def _role_summary(
    role: RoleRow,
    *,
    permission_codes: set[str],
    member_count: int,
) -> TenantRoleSummary:
    return TenantRoleSummary(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        status=role.status,
        permission_codes=sorted(permission_codes),
        member_count=member_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def list_permissions(
    session: Session, *, permissions: frozenset[str]
) -> list[TenantPermissionSummary]:
    _require(permissions, "system.role_manage")
    return [
        TenantPermissionSummary(
            code=row.code,
            module=row.module,
            action=row.action,
            description=row.description,
        )
        for row in repository.list_permissions(session)
        if row.code not in PLATFORM_ADMIN_ONLY_PERMISSION_CODES
    ]


def list_roles(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> list[TenantRoleSummary]:
    _require(permissions, "system.role_manage")
    roles = repository.list_roles(session, tenant_id=tenant_id)
    grants = _permission_codes_by_role(session, tenant_id=tenant_id, roles=roles)
    counts = repository.role_member_counts(session, tenant_id=tenant_id)
    return [
        _role_summary(
            role,
            permission_codes=grants.get(role.id, set()),
            member_count=counts.get(role.id, 0),
        )
        for role in roles
    ]


def list_members(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
) -> list[TenantMemberSummary]:
    _require_any(permissions, "system.user_manage", "system.role_manage")
    members = repository.list_members(session, tenant_id=tenant_id)
    membership_ids = [membership.id for membership, _user in members]
    roles_by_membership: dict[UUID, list[TenantMemberRoleSummary]] = {
        membership_id: [] for membership_id in membership_ids
    }
    for assignment, role in repository.member_role_rows(
        session, tenant_id=tenant_id, membership_ids=membership_ids
    ):
        roles_by_membership.setdefault(assignment.membership_id, []).append(
            TenantMemberRoleSummary(
                id=role.id,
                code=role.code,
                name=role.name,
                is_system=role.is_system,
            )
        )
    return [
        TenantMemberSummary(
            id=membership.id,
            user_id=user.id,
            display_name=user.display_name,
            email=user.email_normalized,
            job_title=membership.job_title,
            status=membership.status,
            permission_version=membership.permission_version,
            roles=roles_by_membership.get(membership.id, []),
            joined_at=membership.joined_at,
            created_at=membership.created_at,
        )
        for membership, user in members
    ]


def _sync_role_permissions(
    session: Session,
    *,
    tenant_id: UUID,
    role: RoleRow,
    permission_rows: list[PermissionRow],
) -> bool:
    desired_ids = {row.id for row in permission_rows}
    existing = {
        row.permission_id: row
        for row in repository.role_permission_rows(
            session, tenant_id=tenant_id, role_ids=[role.id]
        )
    }
    changed = False
    for permission_id, assignment in existing.items():
        if permission_id not in desired_ids and assignment.deleted_at is None:
            mark_deleted(assignment)
            changed = True
    for permission in permission_rows:
        assignment = existing.get(permission.id)
        if assignment is None:
            session.add(
                RolePermissionRow(
                    tenant_id=tenant_id,
                    role_id=role.id,
                    permission_id=permission.id,
                )
            )
            changed = True
        elif assignment.deleted_at is not None:
            restore_deleted(assignment)
            changed = True
    return changed


def create_role(
    session: Session,
    *,
    tenant_id: UUID,
    permissions: frozenset[str],
    request: TenantRoleCreateRequest,
) -> TenantRoleSummary:
    _require(permissions, "system.role_manage")
    if repository.role_code_exists(session, tenant_id=tenant_id, code=request.code):
        raise ApplicationError(
            "ROLE_CODE_CONFLICT",
            "A role with this code already exists in the tenant.",
            kind="conflict",
        )
    permission_rows = _resolve_permission_rows(session, request.permission_codes)
    _require_delegable_permissions(
        permissions, {row.code for row in permission_rows}
    )
    role = RoleRow(
        tenant_id=tenant_id,
        code=request.code,
        name=request.name,
        description=request.description,
        is_system=False,
        status="active",
    )
    session.add(role)
    try:
        session.flush()
        _sync_role_permissions(
            session,
            tenant_id=tenant_id,
            role=role,
            permission_rows=permission_rows,
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "ROLE_CODE_CONFLICT",
            "A role with this code already exists in the tenant.",
            kind="conflict",
        ) from exc
    session.refresh(role)
    return _role_summary(
        role,
        permission_codes={row.code for row in permission_rows},
        member_count=0,
    )


def _actor_permissions_after_role_change(
    session: Session,
    *,
    tenant_id: UUID,
    actor_membership_id: UUID,
    changed_role: RoleRow,
    proposed_permission_codes: set[str],
) -> set[str] | None:
    pairs = repository.member_role_rows(
        session,
        tenant_id=tenant_id,
        membership_ids=[actor_membership_id],
    )
    if not any(role.id == changed_role.id for _assignment, role in pairs):
        return None
    roles = [role for _assignment, role in pairs]
    grants = _permission_codes_by_role(session, tenant_id=tenant_id, roles=roles)
    grants[changed_role.id] = proposed_permission_codes
    return set().union(*(grants.get(role.id, set()) for role in roles))


def update_role(
    session: Session,
    *,
    tenant_id: UUID,
    actor_membership_id: UUID,
    permissions: frozenset[str],
    role_id: UUID,
    request: TenantRoleUpdateRequest,
) -> TenantRoleSummary:
    _require(permissions, "system.role_manage")
    role = repository.get_role_for_update(
        session, tenant_id=tenant_id, role_id=role_id
    )
    if role is None:
        raise ApplicationError("ROLE_NOT_FOUND", "Role was not found.", kind="not_found")
    if role.is_system:
        raise ApplicationError(
            "SYSTEM_ROLE_IMMUTABLE",
            "System roles cannot be edited.",
            kind="conflict",
        )

    current_grants = _permission_codes_by_role(
        session, tenant_id=tenant_id, roles=[role]
    ).get(role.id, set())
    permission_rows: list[PermissionRow] | None = None
    proposed_grants = current_grants
    if request.permission_codes is not None:
        permission_rows = _resolve_permission_rows(session, request.permission_codes)
        proposed_grants = {row.code for row in permission_rows}
        _require_delegable_permissions(permissions, proposed_grants)
        actor_after = _actor_permissions_after_role_change(
            session,
            tenant_id=tenant_id,
            actor_membership_id=actor_membership_id,
            changed_role=role,
            proposed_permission_codes=proposed_grants,
        )
        governance_before = permissions.intersection(
            {"system.user_manage", "system.role_manage"}
        )
        if actor_after is not None and not governance_before.issubset(actor_after):
            raise ApplicationError(
                "SELF_LOCKOUT_FORBIDDEN",
                "You cannot remove your own access-management permissions.",
                kind="conflict",
            )

    if request.name is not None:
        role.name = request.name
    if "description" in request.model_fields_set:
        role.description = request.description
    permissions_changed = False
    if permission_rows is not None:
        permissions_changed = _sync_role_permissions(
            session,
            tenant_id=tenant_id,
            role=role,
            permission_rows=permission_rows,
        )
    if permissions_changed:
        role.updated_at = utcnow()
        for membership_id in repository.membership_ids_for_role(
            session, tenant_id=tenant_id, role_id=role.id
        ):
            membership = repository.get_membership_for_update(
                session, tenant_id=tenant_id, membership_id=membership_id
            )
            if membership is not None:
                membership.permission_version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "ROLE_UPDATE_CONFLICT",
            "The role changed concurrently.",
            kind="conflict",
        ) from exc
    session.refresh(role)
    return _role_summary(
        role,
        permission_codes=proposed_grants,
        member_count=repository.role_member_counts(
            session, tenant_id=tenant_id
        ).get(role.id, 0),
    )


def _roles_effective_permissions(
    session: Session, *, tenant_id: UUID, roles: list[RoleRow]
) -> set[str]:
    grants = _permission_codes_by_role(session, tenant_id=tenant_id, roles=roles)
    return set().union(*(grants.get(role.id, set()) for role in roles))


def _member_summary(
    session: Session, *, tenant_id: UUID, membership_id: UUID
) -> TenantMemberSummary:
    pair = repository.get_member(
        session, tenant_id=tenant_id, membership_id=membership_id
    )
    if pair is None:
        raise ApplicationError(
            "MEMBERSHIP_NOT_FOUND", "Tenant membership was not found.", kind="not_found"
        )
    membership, user = pair
    roles = [
        TenantMemberRoleSummary(
            id=role.id,
            code=role.code,
            name=role.name,
            is_system=role.is_system,
        )
        for _assignment, role in repository.member_role_rows(
            session, tenant_id=tenant_id, membership_ids=[membership_id]
        )
    ]
    return TenantMemberSummary(
        id=membership.id,
        user_id=user.id,
        display_name=user.display_name,
        email=user.email_normalized,
        job_title=membership.job_title,
        status=membership.status,
        permission_version=membership.permission_version,
        roles=roles,
        joined_at=membership.joined_at,
        created_at=membership.created_at,
    )


def update_member_roles(
    session: Session,
    *,
    tenant_id: UUID,
    actor_membership_id: UUID,
    actor_user_id: UUID,
    permissions: frozenset[str],
    membership_id: UUID,
    request: TenantMemberRolesUpdateRequest,
) -> TenantMemberSummary:
    _require(permissions, "system.user_manage")
    _require(permissions, "system.role_manage")
    owner_role = repository.lock_owner_role(session, tenant_id=tenant_id)
    if owner_role is None:
        raise ApplicationError(
            "OWNER_ROLE_REQUIRED",
            "The tenant OWNER system role is unavailable.",
            kind="conflict",
        )
    membership = repository.get_membership_for_update(
        session, tenant_id=tenant_id, membership_id=membership_id
    )
    if membership is None:
        raise ApplicationError(
            "MEMBERSHIP_NOT_FOUND", "Tenant membership was not found.", kind="not_found"
        )
    roles = repository.get_roles_by_ids(
        session, tenant_id=tenant_id, role_ids=request.role_ids
    )
    if len(roles) != len(request.role_ids):
        raise ApplicationError(
            "ROLE_NOT_FOUND",
            "One or more roles do not belong to this tenant.",
            kind="not_found",
        )

    role_codes = {role.code for role in roles}
    delegated_permissions = _roles_effective_permissions(
        session, tenant_id=tenant_id, roles=roles
    )
    _require_delegable_permissions(permissions, delegated_permissions)
    actor_roles = [
        role
        for _assignment, role in repository.member_role_rows(
            session,
            tenant_id=tenant_id,
            membership_ids=[actor_membership_id],
        )
    ]
    actor_is_owner = any(
        role.id == owner_role.id and role.code == "OWNER" for role in actor_roles
    )
    owner_ids = repository.active_owner_membership_ids(session, tenant_id=tenant_id)
    target_is_owner = any(
        role.id == owner_role.id and role.code == "OWNER"
        for _assignment, role in repository.member_role_rows(
            session,
            tenant_id=tenant_id,
            membership_ids=[membership.id],
        )
    )
    proposed_is_owner = "OWNER" in role_codes
    if target_is_owner != proposed_is_owner and not actor_is_owner:
        raise ApplicationError(
            "OWNER_ASSIGNMENT_FORBIDDEN",
            "Only a tenant OWNER may add or remove the OWNER role.",
            kind="forbidden",
        )
    if (
        target_is_owner
        and not proposed_is_owner
        and membership.id in owner_ids
        and owner_ids == {membership.id}
    ):
        raise ApplicationError(
            "LAST_OWNER_REQUIRED",
            "The tenant must retain at least one active OWNER.",
            kind="conflict",
        )
    if membership.id == actor_membership_id:
        required = {"system.user_manage", "system.role_manage"}
        if not required.issubset(delegated_permissions):
            raise ApplicationError(
                "SELF_LOCKOUT_FORBIDDEN",
                "You cannot remove your own member and role management permissions.",
                kind="conflict",
            )

    existing = {
        row.role_id: row
        for row in repository.membership_role_assignments(
            session, tenant_id=tenant_id, membership_id=membership.id
        )
    }
    desired_ids = {role.id for role in roles}
    changed = False
    for role_id, assignment in existing.items():
        if role_id not in desired_ids and assignment.deleted_at is None:
            mark_deleted(assignment)
            changed = True
    for role in roles:
        assignment = existing.get(role.id)
        if assignment is None:
            session.add(
                MembershipRoleRow(
                    tenant_id=tenant_id,
                    membership_id=membership.id,
                    role_id=role.id,
                    assigned_by_user_id=actor_user_id,
                )
            )
            changed = True
        elif assignment.deleted_at is not None:
            restore_deleted(assignment)
            assignment.assigned_by_user_id = actor_user_id
            changed = True
    if changed:
        membership.permission_version += 1
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "MEMBERSHIP_ROLE_CONFLICT",
            "The member roles changed concurrently.",
            kind="conflict",
        ) from exc
    return _member_summary(
        session, tenant_id=tenant_id, membership_id=membership.id
    )
