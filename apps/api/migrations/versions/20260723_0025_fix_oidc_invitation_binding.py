"""Fix the PostgreSQL OIDC invitation membership binding.

Revision ID: 20260723_0025
Revises: 20260723_0024
"""

from alembic import op


revision = "20260723_0025"
down_revision = "20260723_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
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
            v_tenant_id uuid;
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
                display_name = left(
                    COALESCE(NULLIF(btrim(p_display_name), ''), display_name),
                    120
                ),
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

            FOREACH v_tenant_id IN ARRAY p_tenant_ids LOOP
                PERFORM set_config(
                    'app.current_tenant_id',
                    v_tenant_id::text,
                    true
                );
                UPDATE public.memberships AS membership
                SET status = 'active',
                    joined_at = COALESCE(
                        membership.joined_at,
                        CURRENT_TIMESTAMP
                    ),
                    updated_at = CURRENT_TIMESTAMP
                FROM public.tenants AS tenant
                WHERE membership.user_id = p_user_id
                  AND membership.tenant_id = v_tenant_id
                  AND membership.status = 'invited'
                  AND tenant.id = v_tenant_id
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


def downgrade() -> None:
    # Restoring the ambiguous function from 0022 would knowingly break first
    # login on PostgreSQL. The compatible function body therefore remains in
    # place if only the Alembic revision marker is rolled back.
    return
