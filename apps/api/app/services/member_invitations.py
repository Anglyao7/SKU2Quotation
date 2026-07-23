from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ..domain.errors import ApplicationError
from ..identity_models import MembershipRoleRow, MembershipRow, RoleRow, UserRow
from ..model_mixins import utcnow
from .invitation_email_lock import acquire_invitation_email_lock


APPROVED_TENANT_ROLES = frozenset({"OWNER", "ADMIN", "SALES", "PURCHASING"})
INVITED_USER_NAMESPACE = UUID("6ce0be51-e81a-43e4-9f56-f252443ea524")


@dataclass(frozen=True)
class MemberInvitationResult:
    user_id: UUID
    membership_id: UUID
    email: str
    display_name: str
    role: str
    membership_status: str
    created: bool
    identity_already_bound: bool


def _eligible_user(users: list[UserRow], *, email: str) -> UserRow | None:
    if len(users) > 1:
        raise ApplicationError(
            "MEMBER_EMAIL_AMBIGUOUS",
            "Multiple identity records use this email; an operator must resolve them first.",
            kind="conflict",
        )
    if not users:
        return None
    user = users[0]
    if user.deleted_at is not None:
        raise ApplicationError(
            "MEMBER_EMAIL_REQUIRES_REVIEW",
            "A retired identity uses this email; an operator must review it first.",
            kind="conflict",
        )
    pending = user.identity_provider == "pending_oidc" and user.status == "invited"
    bound = user.identity_provider.startswith("oidc:") and user.status == "active"
    if not (pending or bound):
        raise ApplicationError(
            "MEMBER_IDENTITY_NOT_ELIGIBLE",
            "This email belongs to an identity that cannot be invited through OIDC.",
            kind="conflict",
        )
    return user


def _postgres_invite(
    session: Session,
    *,
    actor_user_id: UUID,
    tenant_id: UUID,
    email: str,
    display_name: str,
    role_code: str,
) -> MemberInvitationResult:
    # atc_auth is the narrowly privileged BYPASSRLS identity repository. It
    # performs only the global ambiguity read; all writes remain behind the
    # constrained SECURITY DEFINER function.
    acquire_invitation_email_lock(
        session,
        normalized_email=email,
    )
    users = list(
        session.scalars(
            select(UserRow)
            .where(func.lower(UserRow.email_normalized) == email)
            .execution_options(include_deleted=True)
        ).all()
    )
    user = _eligible_user(users, email=email)
    target_user_id = (
        user.id
        if user is not None
        else uuid5(INVITED_USER_NAMESPACE, f"pending-oidc:{email}")
    )
    try:
        row = session.execute(
            text(
                """
                SELECT *
                FROM public.atc_invite_tenant_member(
                    :actor_user_id,
                    :tenant_id,
                    :target_user_id,
                    :new_membership_id,
                    :email,
                    :display_name,
                    :role_code,
                    :create_user
                )
                """
            ),
            {
                "actor_user_id": actor_user_id,
                "tenant_id": tenant_id,
                "target_user_id": target_user_id,
                "new_membership_id": uuid4(),
                "email": email,
                "display_name": display_name,
                "role_code": role_code,
                "create_user": user is None,
            },
        ).mappings().one()
        session.commit()
    except DBAPIError as exc:
        session.rollback()
        message = str(exc.orig).lower()
        if "different role" in message:
            code = "TENANT_MEMBER_ROLE_CONFLICT"
            safe = "This tenant member already has a different role."
        elif "operator review" in message or "not eligible" in message:
            code = "MEMBER_IDENTITY_NOT_ELIGIBLE"
            safe = "This identity or membership requires operator review."
        elif "tenant must be active" in message:
            code = "TENANT_NOT_ACTIVE"
            safe = "Members can only be invited to an active tenant."
        elif "role is unavailable" in message:
            code = "TENANT_ROLE_UNAVAILABLE"
            safe = "The approved tenant role is unavailable."
        elif "administrator access" in message:
            code = "PLATFORM_ADMIN_REQUIRED"
            safe = "Platform administrator access is required."
        else:
            code = "MEMBER_INVITATION_FAILED"
            safe = "The tenant member invitation could not be created."
        raise ApplicationError(code, safe, kind="conflict") from exc

    return MemberInvitationResult(
        user_id=UUID(str(row["invited_user_id"])),
        membership_id=UUID(str(row["invited_membership_id"])),
        email=email,
        display_name=user.display_name if user is not None else display_name,
        role=role_code,
        membership_status=str(row["invited_membership_status"]),
        created=bool(row["invitation_created"]),
        identity_already_bound=bool(row["identity_already_bound"]),
    )


def _sqlite_invite(
    session: Session,
    *,
    actor_user_id: UUID,
    tenant_id: UUID,
    email: str,
    display_name: str,
    role_code: str,
) -> MemberInvitationResult:
    users = list(
        session.scalars(
            select(UserRow)
            .where(func.lower(UserRow.email_normalized) == email)
            .execution_options(include_deleted=True)
        ).all()
    )
    user = _eligible_user(users, email=email)
    created = False
    if user is None:
        user = UserRow(
            id=uuid5(INVITED_USER_NAMESPACE, f"pending-oidc:{email}"),
            email_normalized=email,
            display_name=display_name,
            identity_provider="pending_oidc",
            identity_subject="",
            status="invited",
            is_platform_admin=False,
        )
        user.identity_subject = f"pending:{user.id}"
        session.add(user)
        session.flush()
        created = True

    identity_already_bound = (
        user.identity_provider.startswith("oidc:") and user.status == "active"
    )
    membership = session.scalar(
        select(MembershipRow)
        .where(
            MembershipRow.tenant_id == tenant_id,
            MembershipRow.user_id == user.id,
        )
        .execution_options(include_deleted=True)
    )
    if membership is None:
        membership = MembershipRow(
            tenant_id=tenant_id,
            user_id=user.id,
            status="active" if identity_already_bound else "invited",
            joined_at=utcnow() if identity_already_bound else None,
        )
        session.add(membership)
        session.flush()
        created = True
    elif membership.deleted_at is not None or membership.status in {"suspended", "removed"}:
        raise ApplicationError(
            "MEMBER_MEMBERSHIP_REQUIRES_REVIEW",
            "This tenant membership requires operator review.",
            kind="conflict",
        )
    elif not identity_already_bound and membership.status != "invited":
        raise ApplicationError(
            "MEMBER_MEMBERSHIP_REQUIRES_REVIEW",
            "The pending identity has an invalid tenant membership.",
            kind="conflict",
        )
    elif identity_already_bound and membership.status == "invited":
        membership.status = "active"
        membership.joined_at = membership.joined_at or utcnow()
        created = True

    role = session.scalar(
        select(RoleRow).where(
            RoleRow.tenant_id == tenant_id,
            RoleRow.code == role_code,
            RoleRow.is_system.is_(True),
            RoleRow.status == "active",
        )
    )
    if role is None:
        raise ApplicationError(
            "TENANT_ROLE_UNAVAILABLE",
            "The approved tenant role is unavailable.",
            kind="conflict",
        )
    assignments = list(
        session.scalars(
            select(MembershipRoleRow)
            .where(
                MembershipRoleRow.tenant_id == tenant_id,
                MembershipRoleRow.membership_id == membership.id,
            )
            .execution_options(include_deleted=True)
        ).all()
    )
    active_assignments = [row for row in assignments if row.deleted_at is None]
    if active_assignments and not any(row.role_id == role.id for row in active_assignments):
        raise ApplicationError(
            "TENANT_MEMBER_ROLE_CONFLICT",
            "This tenant member already has a different role.",
            kind="conflict",
        )
    if not active_assignments:
        if assignments:
            raise ApplicationError(
                "MEMBER_MEMBERSHIP_REQUIRES_REVIEW",
                "A retired tenant role assignment requires operator review.",
                kind="conflict",
            )
        session.add(
            MembershipRoleRow(
                tenant_id=tenant_id,
                membership_id=membership.id,
                role_id=role.id,
                assigned_by_user_id=actor_user_id,
            )
        )
        created = True
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApplicationError(
            "MEMBER_INVITATION_CONFLICT",
            "A concurrent invitation already changed this tenant membership.",
            kind="conflict",
        ) from exc
    return MemberInvitationResult(
        user_id=user.id,
        membership_id=membership.id,
        email=email,
        display_name=user.display_name,
        role=role_code,
        membership_status=membership.status,
        created=created,
        identity_already_bound=identity_already_bound,
    )


def invite_tenant_member(
    session: Session,
    *,
    actor_user_id: UUID,
    tenant_id: UUID,
    email: str,
    display_name: str,
    role_code: str,
) -> MemberInvitationResult:
    normalized_email = email.strip().lower()
    normalized_role = role_code.strip().upper()
    if normalized_role not in APPROVED_TENANT_ROLES:
        raise ApplicationError(
            "TENANT_ROLE_NOT_ALLOWED",
            "Only approved system roles may be assigned.",
            kind="invalid",
        )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        return _postgres_invite(
            session,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            email=normalized_email,
            display_name=display_name.strip(),
            role_code=normalized_role,
        )
    return _sqlite_invite(
        session,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        email=normalized_email,
        display_name=display_name.strip(),
        role_code=normalized_role,
    )
