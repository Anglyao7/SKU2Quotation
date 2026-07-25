"""Add a constrained OIDC invitation-binding capability.

Revision ID: 20260723_0022
Revises: 20260720_0021
"""

from alembic import op


revision = "20260723_0022"
down_revision = "20260720_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_lock_invitation_email(
            p_email text
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            v_email text := lower(btrim(p_email));
        BEGIN
            IF v_email IS NULL
               OR length(v_email) < 3
               OR length(v_email) > 320
               OR v_email !~ '^[^@[:space:]]+@[^@[:space:]]+[.][^@[:space:]]+$'
            THEN
                RAISE EXCEPTION 'invalid invitation email lock request'
                    USING ERRCODE = '22023';
            END IF;

            -- One transaction-level lock serializes every invitation mutation
            -- for this normalized email. It is released only by transaction
            -- commit or rollback; callers cannot accidentally unlock it early.
            PERFORM pg_advisory_xact_lock(hashtextextended(v_email, 0));
        END;
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.atc_lock_invitation_email(text) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_bind_oidc_invitation(
            p_user_id uuid,
            p_email text,
            p_provider text,
            p_subject text,
            p_display_name text,
            p_tenant_ids uuid[]
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            tenant_id uuid;
            affected integer;
        BEGIN
            IF p_provider !~ '^oidc:[0-9a-f]{32}$'
               OR p_subject IS NULL OR length(p_subject) < 1 OR length(p_subject) > 255
               OR p_email IS NULL OR length(p_email) > 320
               OR p_tenant_ids IS NULL OR cardinality(p_tenant_ids) < 1
               OR cardinality(p_tenant_ids) <> (
                    SELECT count(DISTINCT candidate)
                    FROM unnest(p_tenant_ids) AS candidate
               )
            THEN
                RAISE EXCEPTION 'invalid OIDC invitation binding request'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM public.atc_lock_invitation_email(p_email);

            PERFORM set_config('app.current_user_id', p_user_id::text, true);
            PERFORM set_config('app.current_tenant_id', p_tenant_ids[1]::text, true);

            UPDATE public.users
            SET identity_provider = p_provider,
                identity_subject = p_subject,
                display_name = left(COALESCE(NULLIF(btrim(p_display_name), ''), display_name), 120),
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = p_user_id
              AND identity_provider = 'pending_oidc'
              AND status = 'invited'
              AND lower(email_normalized) = lower(btrim(p_email));
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'OIDC invitation is not eligible'
                    USING ERRCODE = 'P0001';
            END IF;

            FOREACH tenant_id IN ARRAY p_tenant_ids LOOP
                PERFORM set_config('app.current_tenant_id', tenant_id::text, true);
                UPDATE public.memberships AS membership
                SET status = 'active',
                    joined_at = COALESCE(joined_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                FROM public.tenants AS tenant
                WHERE membership.user_id = p_user_id
                  AND membership.tenant_id = tenant_id
                  AND membership.status = 'invited'
                  AND tenant.id = tenant_id
                  AND tenant.status = 'active';
                GET DIAGNOSTICS affected = ROW_COUNT;
                IF affected <> 1 THEN
                    RAISE EXCEPTION 'OIDC membership invitation is not eligible'
                        USING ERRCODE = 'P0001';
                END IF;
            END LOOP;
            RETURN true;
        END;
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.atc_bind_oidc_invitation("
        "uuid, text, text, text, text, uuid[]) FROM PUBLIC"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_touch_user_login(
            p_user_id uuid,
            p_provider text,
            p_subject text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            affected integer;
        BEGIN
            PERFORM set_config('app.current_user_id', p_user_id::text, true);
            UPDATE public.users
            SET last_login_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = p_user_id
              AND identity_provider = p_provider
              AND identity_subject = p_subject
              AND status = 'active';
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN affected = 1;
        END;
        $function$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.atc_touch_user_login("
        "uuid, text, text) FROM PUBLIC"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS public.atc_touch_user_login("
            "uuid, text, text)"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS public.atc_bind_oidc_invitation("
            "uuid, text, text, text, text, uuid[])"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS public.atc_lock_invitation_email(text)"
        )
