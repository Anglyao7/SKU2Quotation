"""Allow authenticated platform administrators to manage tenant identities.

Revision ID: 20260720_0021
Revises: 20260720_0020
"""

from alembic import op


revision = "20260720_0021"
down_revision = "20260720_0020"
branch_labels = None
depends_on = None


def _platform_admin_expression() -> str:
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
    return (
        "EXISTS (SELECT 1 FROM users platform_user "
        f"WHERE platform_user.id = {user_id} "
        "AND platform_user.status = 'active' "
        "AND platform_user.is_platform_admin = TRUE)"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    organization_id = "NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    platform_admin = _platform_admin_expression()

    op.execute('DROP POLICY IF EXISTS "organizations_tenant_isolation" ON "organizations"')
    op.execute(
        'CREATE POLICY "organizations_tenant_isolation" ON "organizations" FOR ALL '
        f"USING (id = {organization_id} OR {platform_admin}) "
        f"WITH CHECK (id = {organization_id} OR {platform_admin})"
    )
    op.execute('DROP POLICY IF EXISTS "tenants_tenant_isolation" ON "tenants"')
    op.execute(
        'CREATE POLICY "tenants_tenant_isolation" ON "tenants" FOR ALL '
        f"USING (id = {tenant_id} OR {platform_admin}) "
        f"WITH CHECK (id = {tenant_id} OR {platform_admin})"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    organization_id = "NULLIF(current_setting('app.current_organization_id', true), '')::uuid"
    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"

    op.execute('DROP POLICY IF EXISTS "organizations_tenant_isolation" ON "organizations"')
    op.execute(
        'CREATE POLICY "organizations_tenant_isolation" ON "organizations" FOR ALL '
        f"USING (id = {organization_id}) WITH CHECK (id = {organization_id})"
    )
    op.execute('DROP POLICY IF EXISTS "tenants_tenant_isolation" ON "tenants"')
    op.execute(
        'CREATE POLICY "tenants_tenant_isolation" ON "tenants" FOR ALL '
        f"USING (id = {tenant_id}) WITH CHECK (id = {tenant_id})"
    )
