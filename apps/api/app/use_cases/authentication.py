from __future__ import annotations

from sqlalchemy.orm import Session

from ..auth_schemas import AuthContext, AuthUser, MeResponse, MembershipSummary
from ..domain.errors import ApplicationError
from ..repositories.identity_repository import get_membership, get_tenant
from ..services.auth.dependencies import RequestContext


def _masked_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}***@{domain}"


def get_current_user(session: Session, *, context: RequestContext) -> MeResponse:
    membership = get_membership(session, context.membership_id)
    tenant = get_tenant(session, context.tenant_id)
    if membership is None or tenant is None:
        raise ApplicationError(
            "AUTH_SESSION_EXPIRED",
            "Session context is no longer available.",
            kind="unauthorized",
        )
    user = membership.user
    return MeResponse(
        user=AuthUser(
            id=user.id,
            display_name=user.display_name,
            email=_masked_email(user.email_normalized),
            is_platform_admin=bool(user.is_platform_admin),
        ),
        context=AuthContext(
            tenant_id=tenant.id,
            membership_id=membership.id,
            tenant_name=tenant.name,
            tenant_slug=tenant.slug,
            default_workspace="dashboard",
        ),
        memberships=[
            MembershipSummary(
                id=membership.id,
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_slug=tenant.slug,
                status=membership.status,
            )
        ],
    )
