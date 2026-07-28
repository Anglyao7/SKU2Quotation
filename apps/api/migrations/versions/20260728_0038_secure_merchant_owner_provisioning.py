"""Provision merchant password owners through a least-privilege database function.

Revision ID: 20260728_0038
Revises: 20260728_0037
"""

from __future__ import annotations

from alembic import op


revision = "20260728_0038"
down_revision = "20260728_0037"
branch_labels = None
depends_on = None


FUNCTION_SIGNATURE = (
    "public.atc_provision_tenant_owner("
    "uuid, uuid, uuid, uuid, text, text, text, text, text)"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_provision_tenant_owner(
            p_actor_user_id uuid,
            p_tenant_id uuid,
            p_user_id uuid,
            p_membership_id uuid,
            p_email text,
            p_display_name text,
            p_identity_provider text,
            p_identity_subject text,
            p_login_identifier text
        ) RETURNS TABLE (
            owner_user_id uuid,
            owner_membership_id uuid,
            owner_display_name text,
            owner_login_identifier text,
            owner_email text,
            owner_membership_status text,
            owner_created_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            v_email text := NULLIF(lower(btrim(p_email)), '');
            v_display_name text := btrim(p_display_name);
            v_identity_provider text := btrim(p_identity_provider);
            v_identity_subject text := btrim(p_identity_subject);
            v_login_identifier text := lower(btrim(p_login_identifier));
            v_actor_is_admin boolean := false;
            v_tenant_status text;
            v_owner_role_id uuid;
            v_existing_owner_membership_id uuid;
            v_existing_owner_status text;
            v_created_at timestamptz := CURRENT_TIMESTAMP;
        BEGIN
            IF p_actor_user_id IS NULL
               OR p_tenant_id IS NULL
               OR p_user_id IS NULL
               OR p_membership_id IS NULL
               OR v_display_name IS NULL OR length(v_display_name) < 1 OR length(v_display_name) > 120
               OR v_identity_provider IS NULL OR length(v_identity_provider) < 1 OR length(v_identity_provider) > 50
               OR v_identity_subject IS NULL OR length(v_identity_subject) < 1 OR length(v_identity_subject) > 255
               OR v_login_identifier IS NULL OR length(v_login_identifier) < 3 OR length(v_login_identifier) > 320
               OR (v_email IS NOT NULL AND (length(v_email) > 320 OR v_email !~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'))
            THEN
                RAISE EXCEPTION 'invalid merchant owner provisioning request'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM set_config('app.current_user_id', p_actor_user_id::text, true);
            PERFORM set_config('app.current_tenant_id', p_tenant_id::text, true);

            SELECT u.is_platform_admin
            INTO v_actor_is_admin
            FROM public.users AS u
            WHERE u.id = p_actor_user_id
              AND u.status = 'active'
              AND u.deleted_at IS NULL;
            IF NOT COALESCE(v_actor_is_admin, false) THEN
                RAISE EXCEPTION 'platform administrator access is required'
                    USING ERRCODE = '42501';
            END IF;

            SELECT t.status
            INTO v_tenant_status
            FROM public.tenants AS t
            WHERE t.id = p_tenant_id
              AND t.deleted_at IS NULL;
            IF v_tenant_status IS NULL THEN
                RAISE EXCEPTION 'tenant was not found' USING ERRCODE = 'P0002';
            ELSIF v_tenant_status <> 'active' THEN
                RAISE EXCEPTION 'tenant must be active' USING ERRCODE = 'P0001';
            END IF;

            SELECT r.id
            INTO v_owner_role_id
            FROM public.roles AS r
            WHERE r.tenant_id = p_tenant_id
              AND r.code = 'OWNER'
              AND r.is_system = true
              AND r.status = 'active'
              AND r.deleted_at IS NULL;
            IF v_owner_role_id IS NULL THEN
                RAISE EXCEPTION 'tenant role is unavailable' USING ERRCODE = 'P0001';
            END IF;

            SELECT m.id, m.status
            INTO v_existing_owner_membership_id, v_existing_owner_status
            FROM public.memberships AS m
            JOIN public.membership_roles AS mr
              ON mr.tenant_id = m.tenant_id
             AND mr.membership_id = m.id
             AND mr.deleted_at IS NULL
            WHERE m.tenant_id = p_tenant_id
              AND m.account_scope = 'STAFF'
              AND m.status <> 'removed'
              AND m.deleted_at IS NULL
              AND mr.role_id = v_owner_role_id
            ORDER BY m.created_at, m.id
            LIMIT 1
            FOR UPDATE OF m;
            IF v_existing_owner_membership_id IS NOT NULL THEN
                IF v_existing_owner_status IN ('active', 'suspended') THEN
                    RAISE EXCEPTION 'merchant already has a main account'
                        USING ERRCODE = '23505';
                END IF;
                UPDATE public.memberships
                SET status = 'removed', updated_at = CURRENT_TIMESTAMP
                WHERE id = v_existing_owner_membership_id
                  AND tenant_id = p_tenant_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM public.memberships AS m
                WHERE m.tenant_id = p_tenant_id
                  AND m.login_identifier = v_login_identifier
                  AND m.deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'login account is already used by a member of the merchant'
                    USING ERRCODE = '23505';
            END IF;
            -- `users` is intentionally globally isolated.  The active-email
            -- and provider/subject unique constraints remain the race-safe
            -- conflict authority; never widen this function's read scope.
            PERFORM set_config('app.current_user_id', p_user_id::text, true);

            INSERT INTO public.users (
                id, email_normalized, display_name, identity_provider,
                identity_subject, locale, status, is_platform_admin,
                created_at, updated_at, deleted_at
            ) VALUES (
                p_user_id, v_email, v_display_name, v_identity_provider,
                v_identity_subject, 'zh-CN', 'active', false,
                v_created_at, v_created_at, NULL
            );
            INSERT INTO public.memberships (
                id, tenant_id, user_id, account_scope, login_identifier,
                status, joined_at, permission_version,
                created_at, updated_at, deleted_at
            ) VALUES (
                p_membership_id, p_tenant_id, p_user_id, 'STAFF', v_login_identifier,
                'active', v_created_at, 1,
                v_created_at, v_created_at, NULL
            );
            INSERT INTO public.membership_roles (
                id, tenant_id, membership_id, role_id, assigned_by_user_id,
                created_at, updated_at, deleted_at
            ) VALUES (
                gen_random_uuid(), p_tenant_id, p_membership_id, v_owner_role_id, p_actor_user_id,
                v_created_at, v_created_at, NULL
            );

            RETURN QUERY SELECT
                p_user_id, p_membership_id, v_display_name, v_login_identifier,
                v_email, 'active'::text, v_created_at;
        END;
        $function$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION_SIGNATURE} FROM PUBLIC")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_SIGNATURE}")
