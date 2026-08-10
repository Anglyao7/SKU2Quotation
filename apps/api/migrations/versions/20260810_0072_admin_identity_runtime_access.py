"""Make the active ADMIN merchant identity grant platform access.

Revision ID: 20260810_0072
Revises: 20260810_0071
"""

from __future__ import annotations

from alembic import op


revision = "20260810_0072"
down_revision = "20260810_0071"
branch_labels = None
depends_on = None


FUNCTION_SIGNATURE = (
    "public.atc_grant_tenant_admin_identity(uuid, uuid, uuid)"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_grant_tenant_admin_identity(
            p_actor_user_id uuid,
            p_actor_tenant_id uuid,
            p_target_tenant_id uuid
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            v_actor_is_admin boolean := false;
            v_target_is_admin boolean := false;
            v_target_user_id uuid;
            v_updated integer := 0;
            v_row_count integer := 0;
        BEGIN
            IF p_actor_user_id IS NULL
               OR p_actor_tenant_id IS NULL
               OR p_target_tenant_id IS NULL
            THEN
                RAISE EXCEPTION 'invalid merchant identity synchronization request'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM set_config(
                'app.current_user_id',
                p_actor_user_id::text,
                true
            );
            PERFORM set_config(
                'app.current_tenant_id',
                p_actor_tenant_id::text,
                true
            );

            SELECT EXISTS (
                SELECT 1
                FROM public.memberships AS membership
                JOIN public.tenants AS tenant
                  ON tenant.id = membership.tenant_id
                WHERE membership.user_id = p_actor_user_id
                  AND membership.tenant_id = p_actor_tenant_id
                  AND membership.account_scope = 'STAFF'
                  AND membership.status = 'active'
                  AND membership.deleted_at IS NULL
                  AND tenant.identity_code = 'ADMIN'
                  AND tenant.status = 'active'
                  AND tenant.deleted_at IS NULL
            ) INTO v_actor_is_admin;

            IF NOT COALESCE(v_actor_is_admin, false) THEN
                RAISE EXCEPTION 'administrator merchant identity is required'
                    USING ERRCODE = '42501';
            END IF;

            PERFORM set_config(
                'app.current_tenant_id',
                p_target_tenant_id::text,
                true
            );
            SELECT EXISTS (
                SELECT 1
                FROM public.tenants AS tenant
                WHERE tenant.id = p_target_tenant_id
                  AND tenant.identity_code = 'ADMIN'
                  AND tenant.status = 'active'
                  AND tenant.deleted_at IS NULL
            ) INTO v_target_is_admin;

            IF NOT COALESCE(v_target_is_admin, false) THEN
                RETURN 0;
            END IF;

            FOR v_target_user_id IN
                SELECT DISTINCT membership.user_id
                FROM public.memberships AS membership
                WHERE membership.tenant_id = p_target_tenant_id
                  AND membership.account_scope = 'STAFF'
                  AND membership.status = 'active'
                  AND membership.deleted_at IS NULL
            LOOP
                PERFORM set_config(
                    'app.current_user_id',
                    v_target_user_id::text,
                    true
                );
                UPDATE public.users
                SET is_platform_admin = true,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = v_target_user_id
                  AND status = 'active'
                  AND deleted_at IS NULL
                  AND is_platform_admin = false;
                GET DIAGNOSTICS v_row_count = ROW_COUNT;
                v_updated := v_updated + v_row_count;
            END LOOP;

            RETURN v_updated;
        END;
        $function$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")

    # Existing platform operators were migrated to an ADMIN merchant in 0071.
    # Keep the legacy flag as a database-policy compatibility projection.
    for table_name in ("tenants", "memberships", "users"):
        op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    try:
        op.execute(
            """
            UPDATE public.users AS platform_user
            SET is_platform_admin = true,
                updated_at = CURRENT_TIMESTAMP
            WHERE platform_user.status = 'active'
              AND platform_user.deleted_at IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM public.memberships AS membership
                  JOIN public.tenants AS tenant
                    ON tenant.id = membership.tenant_id
                  WHERE membership.user_id = platform_user.id
                    AND membership.account_scope = 'STAFF'
                    AND membership.status = 'active'
                    AND membership.deleted_at IS NULL
                    AND tenant.identity_code = 'ADMIN'
                    AND tenant.status = 'active'
                    AND tenant.deleted_at IS NULL
              )
            """
        )
    finally:
        for table_name in ("tenants", "memberships", "users"):
            op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}")
