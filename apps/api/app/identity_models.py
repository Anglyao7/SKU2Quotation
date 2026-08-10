from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .model_mixins import AuditTimestampMixin, utcnow
from .tenant_subscriptions import default_sku_limit, default_subscription_expiry
from .tenant_modules import (
    DEFAULT_MERCHANT_IDENTITY,
    DEFAULT_TENANT_MODULE_ACCESS_MODE,
    default_merchant_identity_modules,
    default_tenant_modules,
)


JSON_DOCUMENT = JSON().with_variant(JSONB(none_as_null=True), "postgresql")


def _default_tenant_subscription_expiry(context: object) -> datetime:
    parameters = context.get_current_parameters()  # type: ignore[attr-defined]
    tier = str(parameters.get("subscription_tier") or "TRIAL")
    started_at = parameters.get("started_at") or utcnow()
    return default_subscription_expiry(tier, started_at=started_at)  # type: ignore[arg-type]


def _default_tenant_subscription_sku_limit(context: object) -> int | None:
    parameters = context.get_current_parameters()  # type: ignore[attr-defined]
    tier = str(parameters.get("subscription_tier") or "TRIAL")
    return default_sku_limit(tier)  # type: ignore[arg-type]


class OrganizationRow(AuditTimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'archived')", name="status_allowed"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)

    tenants: Mapped[list["TenantRow"]] = relationship(back_populates="organization")


class MerchantIdentityProfileRow(AuditTimestampMixin, Base):
    """Platform-managed defaults for merchant-visible modules."""

    __tablename__ = "merchant_identity_profiles"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
    )

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    default_modules: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=default_merchant_identity_modules,
        nullable=False,
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TenantRow(AuditTimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'archived')", name="status_allowed"),
        CheckConstraint(
            "module_access_mode IN ('INHERIT', 'CUSTOM')",
            name="module_access_mode_allowed",
        ),
        Index("ix_tenants_organization_status", "organization_id", "status"),
        Index(
            "ix_tenants_identity_module_access",
            "identity_code",
            "module_access_mode",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    default_locale: Mapped[str] = mapped_column(String(20), default="zh-CN", nullable=False)
    default_currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    identity_code: Mapped[str] = mapped_column(
        ForeignKey("merchant_identity_profiles.code", ondelete="RESTRICT"),
        default=DEFAULT_MERCHANT_IDENTITY,
        nullable=False,
    )
    module_access_mode: Mapped[str] = mapped_column(
        String(20),
        default=DEFAULT_TENANT_MODULE_ACCESS_MODE,
        nullable=False,
    )
    enabled_modules: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT,
        default=default_tenant_modules,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False, index=True)

    organization: Mapped[OrganizationRow] = relationship(back_populates="tenants")
    memberships: Mapped[list["MembershipRow"]] = relationship(back_populates="tenant")
    roles: Mapped[list["RoleRow"]] = relationship(back_populates="tenant")
    subscription: Mapped["TenantSubscriptionRow | None"] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TenantSubscriptionRow(AuditTimestampMixin, Base):
    __tablename__ = "tenant_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "subscription_tier IN ('TRIAL', 'STANDARD', 'SILVER', 'ELITE')",
            name="tier_allowed",
        ),
        CheckConstraint(
            "expires_at > started_at",
            name="expiry_after_start",
        ),
        CheckConstraint(
            "sku_limit IS NULL OR sku_limit >= 0",
            name="sku_limit_nonnegative",
        ),
        Index("ix_tenant_subscriptions_tier_expiry", "subscription_tier", "expires_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    subscription_tier: Mapped[str] = mapped_column(
        String(20), default="TRIAL", nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_default_tenant_subscription_expiry,
        nullable=False,
    )
    sku_limit: Mapped[int | None] = mapped_column(
        Integer,
        default=_default_tenant_subscription_sku_limit,
        nullable=True,
    )

    tenant: Mapped[TenantRow] = relationship(back_populates="subscription")


class UserRow(AuditTimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('invited', 'active', 'locked', 'disabled')", name="status_allowed"),
        UniqueConstraint("identity_provider", "identity_subject", name="identity_provider_subject"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    identity_provider: Mapped[str] = mapped_column(String(50), default="local", nullable=False)
    identity_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="zh-CN", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="invited", nullable=False, index=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["MembershipRow"]] = relationship(back_populates="user")


class MembershipRow(AuditTimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("status IN ('invited', 'active', 'suspended', 'removed')", name="status_allowed"),
        CheckConstraint(
            "account_scope IN ('STAFF', 'CUSTOMER_SUBACCOUNT')",
            name="account_scope_allowed",
        ),
        UniqueConstraint("tenant_id", "user_id", name="tenant_user"),
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "login_identifier",
            name="uq_memberships_tenant_login_identifier",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_memberships_tenant_parent_membership",
            ondelete="RESTRICT",
        ),
        Index("ix_memberships_tenant_status", "tenant_id", "status"),
        Index(
            "ix_memberships_tenant_parent_scope",
            "tenant_id",
            "parent_membership_id",
            "account_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_scope: Mapped[str] = mapped_column(
        String(30), default="STAFF", nullable=False
    )
    parent_membership_id: Mapped[UUID | None] = mapped_column(nullable=True)
    login_identifier: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="invited", nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permission_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    # NULL means "use the assigned role as-is". A concrete list is an
    # account-level ceiling and is primarily used by a parent account to give
    # each direct subaccount a different visible/action scope.
    permission_overrides: Mapped[list[str] | None] = mapped_column(
        JSON_DOCUMENT,
        nullable=True,
    )

    tenant: Mapped[TenantRow] = relationship(back_populates="memberships")
    user: Mapped[UserRow] = relationship(back_populates="memberships")
    role_assignments: Mapped[list["MembershipRoleRow"]] = relationship(
        back_populates="membership", cascade="all, delete-orphan"
    )
    auth_sessions: Mapped[list["AuthSessionRow"]] = relationship(
        back_populates="active_membership"
    )


class LocalAccountCredentialRow(AuditTimestampMixin, Base):
    """Locally managed password material used only by the development profile.

    Production credentials remain in the configured identity provider.  Keeping
    this small local-only table lets created customer subaccounts work in the
    demo without weakening the fixed local owner account.
    """

    __tablename__ = "local_account_credentials"
    __table_args__ = (
        UniqueConstraint("identifier_normalized", name="uq_local_account_credentials_identifier"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    identifier_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)


class CustomerAccountAccessEventRow(Base):
    """Append-only activity facts for customer portal subaccounts."""

    __tablename__ = "customer_account_access_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('LOGIN', 'ORDER_SUBMITTED')",
            name="event_type_allowed",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_customer_account_access_events_tenant_membership",
            ondelete="CASCADE",
        ),
        Index(
            "ix_customer_account_access_events_tenant_membership_occurred",
            "tenant_id",
            "membership_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class RoleRow(AuditTimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status_allowed"),
        UniqueConstraint("tenant_id", "code", name="tenant_code"),
        UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_identity"),
        Index("ix_roles_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)

    tenant: Mapped[TenantRow] = relationship(back_populates="roles")
    permission_assignments: Mapped[list["RolePermissionRow"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    member_assignments: Mapped[list["MembershipRoleRow"]] = relationship(
        back_populates="role", cascade="all, delete-orphan", overlaps="role_assignments"
    )


class PermissionRow(AuditTimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("module", "action", name="module_action"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role_assignments: Mapped[list["RolePermissionRow"]] = relationship(
        back_populates="permission", cascade="all, delete-orphan"
    )


class RolePermissionRow(AuditTimestampMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role_id", "permission_id", name="tenant_role_permission"),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="tenant_role",
            ondelete="CASCADE",
        ),
        Index("ix_role_permissions_tenant_role", "tenant_id", "role_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[UUID] = mapped_column(nullable=False)
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[RoleRow] = relationship(back_populates="permission_assignments")
    permission: Mapped[PermissionRow] = relationship(back_populates="role_assignments")


class MembershipRoleRow(AuditTimestampMixin, Base):
    __tablename__ = "membership_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "membership_id", "role_id", name="tenant_membership_role"),
        ForeignKeyConstraint(
            ["tenant_id", "membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="tenant_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["roles.tenant_id", "roles.id"],
            name="tenant_role",
            ondelete="CASCADE",
        ),
        Index("ix_membership_roles_tenant_membership", "tenant_id", "membership_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    role_id: Mapped[UUID] = mapped_column(nullable=False)
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    membership: Mapped[MembershipRow] = relationship(
        back_populates="role_assignments", overlaps="member_assignments"
    )
    role: Mapped[RoleRow] = relationship(
        back_populates="member_assignments", overlaps="membership,role_assignments"
    )


class AuthSessionRow(Base):
    """Revocable server-side session; browser secrets are stored only as hashes."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("rotation_counter >= 0", name="rotation_counter_nonnegative"),
        CheckConstraint("session_version >= 1", name="session_version_positive"),
        CheckConstraint("permission_version >= 1", name="permission_version_positive"),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        UniqueConstraint("token_family_id", name="uq_auth_sessions_token_family"),
        Index("ix_auth_sessions_user_status", "user_id", "revoked_at", "expires_at"),
        Index(
            "ix_auth_sessions_membership_status",
            "active_membership_id",
            "revoked_at",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    active_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="RESTRICT"), nullable=True
    )
    token_family_id: Mapped[UUID] = mapped_column(default=uuid4, nullable=False)
    rotation_counter: Mapped[int] = mapped_column(default=0, nullable=False)
    session_version: Mapped[int] = mapped_column(default=1, nullable=False)
    permission_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[UserRow] = relationship()
    active_membership: Mapped[MembershipRow | None] = relationship(
        back_populates="auth_sessions"
    )
    refresh_tokens: Mapped[list["AuthRefreshTokenRow"]] = relationship(
        back_populates="auth_session",
        cascade="all, delete-orphan",
        foreign_keys="AuthRefreshTokenRow.auth_session_id",
    )


class AuthRefreshTokenRow(Base):
    """One hashed generation in a rotating refresh-token family."""

    __tablename__ = "auth_refresh_tokens"
    __table_args__ = (
        CheckConstraint("sequence_number >= 0", name="sequence_number_nonnegative"),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "(rotation_request_hash IS NULL AND retry_grace_expires_at IS NULL) "
            "OR (rotation_request_hash IS NOT NULL AND retry_grace_expires_at IS NOT NULL)",
            name="retry_metadata_pair",
        ),
        UniqueConstraint("token_hash", name="uq_auth_refresh_tokens_hash"),
        UniqueConstraint(
            "auth_session_id",
            "sequence_number",
            name="uq_auth_refresh_tokens_session_sequence",
        ),
        Index(
            "ix_auth_refresh_tokens_session_status",
            "auth_session_id",
            "revoked_at",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    auth_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_number: Mapped[int] = mapped_column(default=0, nullable=False)
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    rotation_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_grace_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    auth_session: Mapped[AuthSessionRow] = relationship(
        back_populates="refresh_tokens",
        foreign_keys=[auth_session_id],
    )
    replaced_by: Mapped["AuthRefreshTokenRow | None"] = relationship(
        remote_side="AuthRefreshTokenRow.id",
        foreign_keys=[replaced_by_token_id],
    )
