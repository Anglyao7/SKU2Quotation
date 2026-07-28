from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..identity_models import (
    MembershipRoleRow,
    MembershipRow,
    PermissionRow,
    RolePermissionRow,
    RoleRow,
    UserRow,
)


def list_permissions(session: Session) -> list[PermissionRow]:
    return list(
        session.scalars(
            select(PermissionRow).order_by(PermissionRow.module, PermissionRow.action)
        ).all()
    )


def list_roles(session: Session, *, tenant_id: UUID) -> list[RoleRow]:
    return list(
        session.scalars(
            select(RoleRow)
            .where(
                RoleRow.tenant_id == tenant_id,
                RoleRow.status == "active",
                RoleRow.code != "CUSTOMER_SUBACCOUNT",
            )
            .order_by(RoleRow.is_system.desc(), RoleRow.code)
        ).all()
    )


def get_role_for_update(
    session: Session, *, tenant_id: UUID, role_id: UUID
) -> RoleRow | None:
    return session.scalar(
        select(RoleRow)
        .where(RoleRow.tenant_id == tenant_id, RoleRow.id == role_id)
        .with_for_update()
    )


def role_code_exists(session: Session, *, tenant_id: UUID, code: str) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(RoleRow)
            .where(RoleRow.tenant_id == tenant_id, RoleRow.code == code)
            .execution_options(include_deleted=True)
        )
    )


def role_permission_rows(
    session: Session, *, tenant_id: UUID, role_ids: list[UUID]
) -> list[RolePermissionRow]:
    if not role_ids:
        return []
    return list(
        session.scalars(
            select(RolePermissionRow)
            .where(
                RolePermissionRow.tenant_id == tenant_id,
                RolePermissionRow.role_id.in_(role_ids),
            )
            .execution_options(include_deleted=True)
        ).all()
    )


def role_member_counts(
    session: Session, *, tenant_id: UUID
) -> dict[UUID, int]:
    rows = session.execute(
        select(MembershipRoleRow.role_id, func.count(func.distinct(MembershipRoleRow.membership_id)))
        .join(
            MembershipRow,
            and_(
                MembershipRow.tenant_id == MembershipRoleRow.tenant_id,
                MembershipRow.id == MembershipRoleRow.membership_id,
            ),
        )
        .where(
            MembershipRoleRow.tenant_id == tenant_id,
            MembershipRow.status.in_(("active", "invited")),
            MembershipRow.account_scope == "STAFF",
        )
        .group_by(MembershipRoleRow.role_id)
    ).all()
    return {role_id: int(count) for role_id, count in rows}


def list_members(
    session: Session, *, tenant_id: UUID
) -> list[tuple[MembershipRow, UserRow]]:
    return list(
        session.execute(
            select(MembershipRow, UserRow)
            .join(UserRow, UserRow.id == MembershipRow.user_id)
            .where(
                MembershipRow.tenant_id == tenant_id,
                MembershipRow.status.in_(("active", "invited", "suspended")),
                MembershipRow.account_scope == "STAFF",
            )
            .order_by(MembershipRow.status, UserRow.display_name, MembershipRow.id)
        ).all()
    )


def get_member(
    session: Session, *, tenant_id: UUID, membership_id: UUID
) -> tuple[MembershipRow, UserRow] | None:
    return session.execute(
        select(MembershipRow, UserRow)
        .join(UserRow, UserRow.id == MembershipRow.user_id)
        .where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.id == membership_id,
            MembershipRow.account_scope == "STAFF",
        )
    ).one_or_none()


def member_role_rows(
    session: Session, *, tenant_id: UUID, membership_ids: list[UUID]
) -> list[tuple[MembershipRoleRow, RoleRow]]:
    if not membership_ids:
        return []
    return list(
        session.execute(
            select(MembershipRoleRow, RoleRow)
            .join(
                RoleRow,
                and_(
                    RoleRow.tenant_id == MembershipRoleRow.tenant_id,
                    RoleRow.id == MembershipRoleRow.role_id,
                ),
            )
            .where(
                MembershipRoleRow.tenant_id == tenant_id,
                MembershipRoleRow.membership_id.in_(membership_ids),
                RoleRow.status == "active",
            )
            .order_by(RoleRow.is_system.desc(), RoleRow.code)
        ).all()
    )


def get_membership_for_update(
    session: Session, *, tenant_id: UUID, membership_id: UUID
) -> MembershipRow | None:
    return session.scalar(
        select(MembershipRow)
        .where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.id == membership_id,
            MembershipRow.status.in_(("active", "invited")),
            MembershipRow.account_scope == "STAFF",
        )
        .with_for_update()
    )


def get_roles_by_ids(
    session: Session, *, tenant_id: UUID, role_ids: list[UUID]
) -> list[RoleRow]:
    if not role_ids:
        return []
    return list(
        session.scalars(
            select(RoleRow).where(
                RoleRow.tenant_id == tenant_id,
                RoleRow.id.in_(role_ids),
                RoleRow.status == "active",
                RoleRow.code != "CUSTOMER_SUBACCOUNT",
            )
        ).all()
    )


def lock_owner_role(session: Session, *, tenant_id: UUID) -> RoleRow | None:
    """Serialize every OWNER membership change on one tenant-scoped row."""

    return session.scalar(
        select(RoleRow)
        .where(
            RoleRow.tenant_id == tenant_id,
            RoleRow.code == "OWNER",
            RoleRow.is_system.is_(True),
            RoleRow.status == "active",
        )
        .with_for_update()
    )


def membership_role_assignments(
    session: Session, *, tenant_id: UUID, membership_id: UUID
) -> list[MembershipRoleRow]:
    return list(
        session.scalars(
            select(MembershipRoleRow)
            .where(
                MembershipRoleRow.tenant_id == tenant_id,
                MembershipRoleRow.membership_id == membership_id,
            )
            .with_for_update()
            .execution_options(include_deleted=True)
        ).all()
    )


def membership_ids_for_role(
    session: Session, *, tenant_id: UUID, role_id: UUID
) -> list[UUID]:
    return list(
        session.scalars(
            select(MembershipRoleRow.membership_id)
            .join(
                MembershipRow,
                and_(
                    MembershipRow.tenant_id == MembershipRoleRow.tenant_id,
                    MembershipRow.id == MembershipRoleRow.membership_id,
                ),
            )
            .where(
                MembershipRoleRow.tenant_id == tenant_id,
                MembershipRoleRow.role_id == role_id,
                MembershipRow.status.in_(("active", "invited")),
            )
        ).all()
    )


def active_owner_membership_ids(
    session: Session, *, tenant_id: UUID
) -> set[UUID]:
    return set(
        session.scalars(
            select(MembershipRoleRow.membership_id)
            .join(
                MembershipRow,
                and_(
                    MembershipRow.tenant_id == MembershipRoleRow.tenant_id,
                    MembershipRow.id == MembershipRoleRow.membership_id,
                ),
            )
            .join(
                RoleRow,
                and_(
                    RoleRow.tenant_id == MembershipRoleRow.tenant_id,
                    RoleRow.id == MembershipRoleRow.role_id,
                ),
            )
            .where(
                MembershipRoleRow.tenant_id == tenant_id,
                MembershipRow.status == "active",
                RoleRow.code == "OWNER",
                RoleRow.is_system.is_(True),
                RoleRow.status == "active",
            )
        ).all()
    )
