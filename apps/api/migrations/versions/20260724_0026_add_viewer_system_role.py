"""Allow the read-only VIEWER role in constrained tenant invitations.

Revision ID: 20260724_0026
Revises: 20260723_0025
"""

from alembic import op


revision = "20260724_0026"
down_revision = "20260723_0025"
branch_labels = None
depends_on = None


FUNCTION_SIGNATURE = (
    "public.atc_invite_tenant_member("
    "uuid, uuid, uuid, uuid, text, text, text, boolean)"
)


def _replace_role_allowlist(old: str, new: str) -> None:
    op.execute(
        f"""
        DO $migration$
        DECLARE
            v_function regprocedure := to_regprocedure('{FUNCTION_SIGNATURE}');
            v_definition text;
            v_updated text;
        BEGIN
            IF v_function IS NULL THEN
                RAISE EXCEPTION 'atc_invite_tenant_member function is missing';
            END IF;
            SELECT pg_get_functiondef(v_function) INTO v_definition;
            v_updated := replace(v_definition, $old${old}$old$, $new${new}$new$);
            IF v_updated = v_definition THEN
                RAISE EXCEPTION 'tenant invitation role allowlist did not match';
            END IF;
            EXECUTE v_updated;
        END;
        $migration$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")


def _provision_viewer_for_existing_tenants() -> None:
    # The migration role owns these FORCE-RLS tables but is deliberately
    # NOBYPASSRLS. Temporarily dropping FORCE lets the owner reconcile every
    # tenant in this one transactional migration; RLS remains enabled and FORCE
    # is restored before the migration commits.
    op.execute("ALTER TABLE public.tenants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.roles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.role_permissions NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        INSERT INTO public.permissions (
            id, code, module, action, description, created_at, updated_at, deleted_at
        ) VALUES
            (gen_random_uuid(), 'product.view', 'product', 'view', 'View products', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'supplier.view', 'supplier', 'view', 'View suppliers', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'customer.view', 'customer', 'view', 'View customers', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'inquiry.view', 'inquiry', 'view', 'View inquiries', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'quotation.view', 'quotation', 'view', 'View quotations', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'catalog.view', 'catalog', 'view', 'View catalogs', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL),
            (gen_random_uuid(), 'order.view', 'order', 'view', 'View orders', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL)
        ON CONFLICT (code) DO UPDATE
        SET deleted_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """
    )
    op.execute(
        """
        DO $provision$
        DECLARE
            v_tenant_id uuid;
            v_role_id uuid;
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM public.roles
                WHERE code = 'VIEWER'
                  AND is_system = false
            ) THEN
                RAISE EXCEPTION
                    'custom VIEWER role conflicts with the managed system role';
            END IF;

            FOR v_tenant_id IN
                SELECT id
                FROM public.tenants
                WHERE deleted_at IS NULL
            LOOP
                INSERT INTO public.roles (
                    id, tenant_id, code, name, description, is_system, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    gen_random_uuid(), v_tenant_id, 'VIEWER', 'Viewer',
                    'Read-only access to tenant operational data.',
                    true, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL
                )
                ON CONFLICT (tenant_id, code) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    is_system = true,
                    status = 'active',
                    deleted_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id INTO v_role_id;

                INSERT INTO public.role_permissions (
                    id, tenant_id, role_id, permission_id,
                    created_at, updated_at, deleted_at
                )
                SELECT
                    gen_random_uuid(),
                    v_tenant_id,
                    v_role_id,
                    permission.id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    NULL
                FROM public.permissions AS permission
                WHERE permission.code IN (
                    'product.view', 'supplier.view', 'customer.view',
                    'inquiry.view', 'quotation.view', 'catalog.view', 'order.view'
                )
                  AND permission.deleted_at IS NULL
                ON CONFLICT (tenant_id, role_id, permission_id) DO UPDATE
                SET deleted_at = NULL,
                    updated_at = CURRENT_TIMESTAMP;

                UPDATE public.role_permissions AS assignment
                SET deleted_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE assignment.tenant_id = v_tenant_id
                  AND assignment.role_id = v_role_id
                  AND assignment.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.permissions AS permission
                      WHERE permission.id = assignment.permission_id
                        AND permission.code IN (
                            'product.view', 'supplier.view', 'customer.view',
                            'inquiry.view', 'quotation.view', 'catalog.view',
                            'order.view'
                        )
                        AND permission.deleted_at IS NULL
                  );
            END LOOP;
        END;
        $provision$
        """
    )
    op.execute("ALTER TABLE public.role_permissions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.roles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.tenants FORCE ROW LEVEL SECURITY")


def _enable_tenant_member_directory_visibility() -> None:
    """Expose tenant peers for SELECT while keeping every user write self-only."""

    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
    directory_visibility = (
        f"id = {user_id} OR EXISTS ("
        "SELECT 1 FROM public.memberships AS membership "
        f"WHERE membership.user_id = users.id "
        f"AND membership.tenant_id = {tenant_id} "
        "AND membership.status IN ('active', 'invited', 'suspended') "
        "AND membership.deleted_at IS NULL"
        ")"
    )
    self_only = f"id = {user_id}"
    op.execute('DROP POLICY IF EXISTS "users_tenant_visibility" ON public.users')
    op.execute('DROP POLICY IF EXISTS "users_self_mutation" ON public.users')
    op.execute(
        'CREATE POLICY "users_tenant_visibility" ON public.users '
        f"FOR SELECT USING ({directory_visibility})"
    )
    op.execute(
        'CREATE POLICY "users_self_mutation" ON public.users '
        f"FOR ALL USING ({self_only}) WITH CHECK ({self_only})"
    )


def _restore_active_member_user_policy() -> None:
    """Restore the pre-0026 combined visibility/write policy."""

    tenant_id = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.current_user_id', true), '')::uuid"
    visibility = (
        f"id = {user_id} OR EXISTS ("
        "SELECT 1 FROM public.memberships AS membership "
        f"WHERE membership.user_id = users.id "
        f"AND membership.tenant_id = {tenant_id} "
        "AND membership.status = 'active' "
        "AND membership.deleted_at IS NULL"
        ")"
    )
    op.execute('DROP POLICY IF EXISTS "users_tenant_visibility" ON public.users')
    op.execute('DROP POLICY IF EXISTS "users_self_mutation" ON public.users')
    op.execute(
        'CREATE POLICY "users_tenant_visibility" ON public.users '
        f"FOR ALL USING ({visibility}) WITH CHECK (id = {user_id})"
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _replace_role_allowlist(
        "v_role_code NOT IN ('OWNER', 'ADMIN', 'SALES', 'PURCHASING')",
        "v_role_code NOT IN ('OWNER', 'ADMIN', 'SALES', 'PURCHASING', 'VIEWER')",
    )
    _provision_viewer_for_existing_tenants()
    _enable_tenant_member_directory_visibility()


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _restore_active_member_user_policy()
    _replace_role_allowlist(
        "v_role_code NOT IN ('OWNER', 'ADMIN', 'SALES', 'PURCHASING', 'VIEWER')",
        "v_role_code NOT IN ('OWNER', 'ADMIN', 'SALES', 'PURCHASING')",
    )
