"""Phase 1 SaaS identity, tenant, RBAC, and PostgreSQL RLS foundation.

Revision ID: 20260718_0001
Revises: 20260718_0000
Requirements: DATA-001, DATA-002, PRD-019-001, PRD-020-001
"""
from alembic import op
import sqlalchemy as sa


revision = "20260718_0001"
down_revision = "20260718_0000"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _uuid() -> sa.Uuid:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('active', 'suspended', 'archived')", name="ck_organizations_status_allowed"),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("code", name="uq_organizations_code"),
    )
    op.create_index("ix_organizations_status", "organizations", ["status"])

    op.create_table(
        "tenants",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("default_locale", sa.String(20), nullable=False),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('active', 'suspended', 'archived')", name="ck_tenants_status_allowed"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_tenants_organization_id_organizations", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.create_index("ix_tenants_organization_status", "tenants", ["organization_id", "status"])

    op.create_table(
        "users",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("identity_provider", sa.String(50), nullable=False),
        sa.Column("identity_subject", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('invited', 'active', 'locked', 'disabled')", name="ck_users_status_allowed"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("identity_provider", "identity_subject", name="identity_provider_subject"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "permissions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
        sa.UniqueConstraint("module", "action", name="module_action"),
    )
    op.create_index("ix_permissions_module", "permissions", ["module"])

    op.create_table(
        "memberships",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("job_title", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('invited', 'active', 'suspended', 'removed')", name="ck_memberships_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_memberships_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "user_id", name="tenant_user"),
    )
    op.create_index("ix_memberships_tenant_status", "memberships", ["tenant_id", "status"])

    op.create_table(
        "roles",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_roles_status_allowed"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_roles_tenant_id_tenants", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("tenant_id", "code", name="tenant_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_identity"),
    )
    op.create_index("ix_roles_tenant_status", "roles", ["tenant_id", "status"])

    op.create_table(
        "role_permissions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("role_id", _uuid(), nullable=False),
        sa.Column("permission_id", _uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_role_permissions_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="tenant_role", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], name="fk_role_permissions_permission_id_permissions", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_role_permissions"),
        sa.UniqueConstraint("tenant_id", "role_id", "permission_id", name="tenant_role_permission"),
    )
    op.create_index("ix_role_permissions_tenant_role", "role_permissions", ["tenant_id", "role_id"])

    op.create_table(
        "membership_roles",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("tenant_id", _uuid(), nullable=False),
        sa.Column("membership_id", _uuid(), nullable=False),
        sa.Column("role_id", _uuid(), nullable=False),
        sa.Column("assigned_by_user_id", _uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_membership_roles_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"], name="tenant_membership", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="tenant_role", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], name="fk_membership_roles_assigned_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_roles"),
        sa.UniqueConstraint("tenant_id", "membership_id", "role_id", name="tenant_membership_role"),
    )
    op.create_index("ix_membership_roles_tenant_membership", "membership_roles", ["tenant_id", "membership_id"])

    if op.get_bind().dialect.name == "postgresql":
        _enable_postgresql_rls()


def _enable_postgresql_rls() -> None:
    organization_id = "NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"

    policies = {
        "organizations": (f"id = {organization_id}", f"id = {organization_id}"),
        "tenants": (f"id = {tenant_id}", f"id = {tenant_id}"),
        "memberships": (f"tenant_id = {tenant_id}", f"tenant_id = {tenant_id}"),
        "roles": (f"tenant_id = {tenant_id}", f"tenant_id = {tenant_id}"),
        "role_permissions": (f"tenant_id = {tenant_id}", f"tenant_id = {tenant_id}"),
        "membership_roles": (f"tenant_id = {tenant_id}", f"tenant_id = {tenant_id}"),
    }
    for table, (using, check) in policies.items():
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_tenant_isolation" ON "{table}" '
            f'FOR ALL USING ({using}) WITH CHECK ({check})'
        )

    user_visibility = (
        f"id = {user_id} OR EXISTS ("
        "SELECT 1 FROM memberships m "
        f"WHERE m.user_id = users.id AND m.tenant_id = {tenant_id} AND m.status = 'active'"
        ")"
    )
    op.execute('ALTER TABLE "users" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "users" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "users_tenant_visibility" ON "users" '
        f'FOR ALL USING ({user_visibility}) WITH CHECK (id = {user_id})'
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "membership_roles", "role_permissions", "roles", "memberships", "tenants", "organizations"
        ):
            op.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
        op.execute('DROP POLICY IF EXISTS "users_tenant_visibility" ON "users"')

    op.drop_table("membership_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("memberships")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("organizations")
