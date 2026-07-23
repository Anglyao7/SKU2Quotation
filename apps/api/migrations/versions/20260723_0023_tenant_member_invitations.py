"""Add a constrained platform-admin tenant invitation capability.

Revision ID: 20260723_0023
Revises: 20260723_0022
"""

from alembic import op


revision = "20260723_0023"
down_revision = "20260723_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        DO $block$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM public.users
                WHERE deleted_at IS NULL
                  AND email_normalized IS NOT NULL
                GROUP BY lower(email_normalized)
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'cannot enforce unique active normalized user email: duplicates require review'
                    USING ERRCODE = '23505';
            END IF;
        END;
        $block$
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_users_active_normalized_email
        ON public.users (lower(email_normalized))
        WHERE deleted_at IS NULL AND email_normalized IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_invite_tenant_member(
            p_actor_user_id uuid,
            p_tenant_id uuid,
            p_target_user_id uuid,
            p_new_membership_id uuid,
            p_email text,
            p_display_name text,
            p_role_code text,
            p_create_user boolean
        ) RETURNS TABLE (
            invited_user_id uuid,
            invited_membership_id uuid,
            invited_membership_status text,
            invitation_created boolean,
            identity_already_bound boolean
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            v_email text := lower(btrim(p_email));
            v_display_name text := btrim(p_display_name);
            v_role_code text := upper(btrim(p_role_code));
            v_actor_is_admin boolean := false;
            v_tenant_status text;
            v_role_id uuid;
            v_provider text;
            v_user_status text;
            v_user_deleted_at timestamptz;
            v_membership_id uuid;
            v_membership_status text;
            v_membership_deleted_at timestamptz;
            v_assignment_count integer := 0;
            v_requested_assignment_count integer := 0;
            v_created boolean := false;
            v_identity_bound boolean := false;
        BEGIN
            IF p_actor_user_id IS NULL
               OR p_tenant_id IS NULL
               OR p_target_user_id IS NULL
               OR p_new_membership_id IS NULL
               OR v_email IS NULL
               OR length(v_email) < 3
               OR length(v_email) > 320
               OR v_email !~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
               OR v_display_name IS NULL
               OR length(v_display_name) < 1
               OR length(v_display_name) > 120
               OR v_role_code NOT IN ('OWNER', 'ADMIN', 'SALES', 'PURCHASING')
            THEN
                RAISE EXCEPTION 'invalid tenant member invitation request'
                    USING ERRCODE = '22023';
            END IF;

            -- Use the same normalized-email transaction lock as first OIDC
            -- binding before reading or changing any invitation identity.
            PERFORM public.atc_lock_invitation_email(v_email);

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
                RAISE EXCEPTION 'tenant was not found'
                    USING ERRCODE = 'P0002';
            ELSIF v_tenant_status <> 'active' THEN
                RAISE EXCEPTION 'tenant must be active'
                    USING ERRCODE = 'P0001';
            END IF;

            SELECT r.id
            INTO v_role_id
            FROM public.roles AS r
            WHERE r.tenant_id = p_tenant_id
              AND r.code = v_role_code
              AND r.is_system = true
              AND r.status = 'active'
              AND r.deleted_at IS NULL;
            IF v_role_id IS NULL THEN
                RAISE EXCEPTION 'approved tenant role is unavailable'
                    USING ERRCODE = 'P0001';
            END IF;

            -- The users policy allows a user to see/write itself. The actor was
            -- already independently verified above, before changing context.
            PERFORM set_config('app.current_user_id', p_target_user_id::text, true);
            IF p_create_user THEN
                IF EXISTS (SELECT 1 FROM public.users AS u WHERE u.id = p_target_user_id) THEN
                    RAISE EXCEPTION 'target user already exists'
                        USING ERRCODE = '23505';
                END IF;
                INSERT INTO public.users (
                    id,
                    email_normalized,
                    display_name,
                    identity_provider,
                    identity_subject,
                    locale,
                    status,
                    is_platform_admin,
                    created_at,
                    updated_at,
                    deleted_at
                ) VALUES (
                    p_target_user_id,
                    v_email,
                    v_display_name,
                    'pending_oidc',
                    'pending:' || p_target_user_id::text,
                    'zh-CN',
                    'invited',
                    false,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    NULL
                );
                v_provider := 'pending_oidc';
                v_user_status := 'invited';
                v_created := true;
            ELSE
                SELECT u.identity_provider, u.status, u.deleted_at
                INTO v_provider, v_user_status, v_user_deleted_at
                FROM public.users AS u
                WHERE u.id = p_target_user_id
                  AND lower(u.email_normalized) = v_email;
                IF v_provider IS NULL OR v_user_deleted_at IS NOT NULL THEN
                    RAISE EXCEPTION 'invited identity requires operator review'
                        USING ERRCODE = 'P0001';
                END IF;
                IF v_provider = 'pending_oidc' AND v_user_status = 'invited' THEN
                    v_identity_bound := false;
                ELSIF v_provider ~ '^oidc:[0-9a-f]{32}$' AND v_user_status = 'active' THEN
                    v_identity_bound := true;
                ELSE
                    RAISE EXCEPTION 'invited identity is not eligible'
                        USING ERRCODE = 'P0001';
                END IF;
            END IF;

            SELECT m.id, m.status, m.deleted_at
            INTO v_membership_id, v_membership_status, v_membership_deleted_at
            FROM public.memberships AS m
            WHERE m.tenant_id = p_tenant_id
              AND m.user_id = p_target_user_id;

            IF v_membership_id IS NULL THEN
                v_membership_id := p_new_membership_id;
                v_membership_status := CASE
                    WHEN v_identity_bound THEN 'active'
                    ELSE 'invited'
                END;
                INSERT INTO public.memberships (
                    id,
                    tenant_id,
                    user_id,
                    status,
                    joined_at,
                    permission_version,
                    created_at,
                    updated_at,
                    deleted_at
                ) VALUES (
                    v_membership_id,
                    p_tenant_id,
                    p_target_user_id,
                    v_membership_status,
                    CASE WHEN v_identity_bound THEN CURRENT_TIMESTAMP ELSE NULL END,
                    1,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    NULL
                );
                v_created := true;
            ELSE
                IF v_membership_deleted_at IS NOT NULL
                   OR v_membership_status IN ('suspended', 'removed')
                THEN
                    RAISE EXCEPTION 'existing tenant membership requires operator review'
                        USING ERRCODE = 'P0001';
                END IF;
                IF NOT v_identity_bound AND v_membership_status <> 'invited' THEN
                    RAISE EXCEPTION 'pending identity has an invalid membership state'
                        USING ERRCODE = 'P0001';
                END IF;
                IF v_identity_bound AND v_membership_status = 'invited' THEN
                    UPDATE public.memberships
                    SET status = 'active',
                        joined_at = COALESCE(joined_at, CURRENT_TIMESTAMP),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = v_membership_id
                      AND tenant_id = p_tenant_id;
                    v_membership_status := 'active';
                    v_created := true;
                END IF;
            END IF;

            SELECT
                count(*) FILTER (WHERE mr.deleted_at IS NULL),
                count(*) FILTER (
                    WHERE mr.role_id = v_role_id AND mr.deleted_at IS NULL
                )
            INTO v_assignment_count, v_requested_assignment_count
            FROM public.membership_roles AS mr
            WHERE mr.tenant_id = p_tenant_id
              AND mr.membership_id = v_membership_id;

            IF v_assignment_count > 0 AND v_requested_assignment_count = 0 THEN
                RAISE EXCEPTION 'tenant member already has a different role'
                    USING ERRCODE = 'P0001';
            ELSIF v_requested_assignment_count = 0 THEN
                INSERT INTO public.membership_roles (
                    id,
                    tenant_id,
                    membership_id,
                    role_id,
                    assigned_by_user_id,
                    created_at,
                    updated_at,
                    deleted_at
                ) VALUES (
                    gen_random_uuid(),
                    p_tenant_id,
                    v_membership_id,
                    v_role_id,
                    p_actor_user_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    NULL
                );
                v_created := true;
            END IF;

            RETURN QUERY SELECT
                p_target_user_id,
                v_membership_id,
                v_membership_status,
                v_created,
                v_identity_bound;
        END;
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.atc_invite_tenant_member("
        "uuid, uuid, uuid, uuid, text, text, text, boolean) FROM PUBLIC"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS public.atc_invite_tenant_member("
            "uuid, uuid, uuid, uuid, text, text, text, boolean)"
        )
        op.execute("DROP INDEX IF EXISTS public.uq_users_active_normalized_email")
