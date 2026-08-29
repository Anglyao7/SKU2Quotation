"""Provision customer subaccounts through a least-privilege database function.

Revision ID: 20260829_0118
Revises: 20260827_0117
"""

from __future__ import annotations

from alembic import op


revision = "20260829_0118"
down_revision = "20260827_0117"
branch_labels = None
depends_on = None


FUNCTION_SIGNATURE = (
    "public.atc_provision_customer_subaccount("
    "uuid, uuid, uuid, uuid, uuid, text, text, text, text, text, jsonb)"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.atc_provision_customer_subaccount(
            p_actor_user_id uuid,
            p_parent_membership_id uuid,
            p_tenant_id uuid,
            p_user_id uuid,
            p_membership_id uuid,
            p_email text,
            p_display_name text,
            p_identity_provider text,
            p_identity_subject text,
            p_login_identifier text,
            p_permission_overrides jsonb
        ) RETURNS TABLE (
            subaccount_user_id uuid,
            subaccount_membership_id uuid,
            subaccount_display_name text,
            subaccount_login_identifier text,
            subaccount_email text,
            subaccount_membership_status text,
            subaccount_created_at timestamptz
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
            v_tenant_status text;
            v_portal_role_id uuid;
            v_created_at timestamptz := CURRENT_TIMESTAMP;
        BEGIN
            IF p_actor_user_id IS NULL
               OR p_parent_membership_id IS NULL
               OR p_tenant_id IS NULL
               OR p_user_id IS NULL
               OR p_membership_id IS NULL
               OR v_display_name IS NULL OR length(v_display_name) < 1 OR length(v_display_name) > 120
               OR v_identity_provider IS NULL OR length(v_identity_provider) < 1 OR length(v_identity_provider) > 50
               OR v_identity_subject IS NULL OR length(v_identity_subject) < 1 OR length(v_identity_subject) > 255
               OR v_login_identifier IS NULL OR length(v_login_identifier) < 2 OR length(v_login_identifier) > 320
               OR (v_email IS NOT NULL AND (length(v_email) > 320 OR position('@' IN v_email) < 2))
               OR p_permission_overrides IS NULL
               OR jsonb_typeof(p_permission_overrides) <> 'array'
            THEN
                RAISE EXCEPTION 'invalid customer subaccount provisioning request'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM set_config('app.current_user_id', p_actor_user_id::text, true);
            PERFORM set_config('app.current_tenant_id', p_tenant_id::text, true);

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

            IF NOT EXISTS (
                SELECT 1
                FROM public.memberships AS membership
                JOIN public.membership_roles AS membership_role
                  ON membership_role.tenant_id = membership.tenant_id
                 AND membership_role.membership_id = membership.id
                 AND membership_role.deleted_at IS NULL
                JOIN public.roles AS role
                  ON role.tenant_id = membership_role.tenant_id
                 AND role.id = membership_role.role_id
                 AND role.status = 'active'
                 AND role.deleted_at IS NULL
                JOIN public.role_permissions AS role_permission
                  ON role_permission.tenant_id = role.tenant_id
                 AND role_permission.role_id = role.id
                 AND role_permission.deleted_at IS NULL
                JOIN public.permissions AS permission
                  ON permission.id = role_permission.permission_id
                 AND permission.code = 'customer_portal.subaccount_manage'
                 AND permission.deleted_at IS NULL
                WHERE membership.id = p_parent_membership_id
                  AND membership.tenant_id = p_tenant_id
                  AND membership.user_id = p_actor_user_id
                  AND membership.account_scope = 'STAFF'
                  AND membership.status = 'active'
                  AND membership.deleted_at IS NULL
                  AND (
                      membership.permission_overrides IS NULL
                      OR membership.permission_overrides @> '["customer_portal.subaccount_manage"]'::jsonb
                  )
            ) THEN
                RAISE EXCEPTION 'parent account cannot manage subaccounts'
                    USING ERRCODE = '42501';
            END IF;

            IF NOT p_permission_overrides @> '["customer_portal.access"]'::jsonb
               OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(p_permission_overrides) AS requested(code)
                    LEFT JOIN public.permissions AS permission
                      ON permission.code = requested.code
                     AND permission.deleted_at IS NULL
                    WHERE permission.id IS NULL
                       OR NOT (
                            permission.module IN (
                                'product', 'catalog', 'customer', 'inquiry',
                                'quotation', 'order', 'announcement', 'support'
                            )
                            OR permission.code IN (
                                'customer_portal.access',
                                'customer_portal.order_create',
                                'customer_portal.order_view_self'
                            )
                       )
                       OR permission.code IN (
                            'product.cost.read', 'product.cost.write',
                            'supplier.view', 'supplier.manage',
                            'system.user_manage', 'system.role_manage', 'system.settings_manage',
                            'customer_portal.subaccount_manage',
                            'analytics.view',
                            'inventory.view', 'inventory.adjust', 'inventory.purchase',
                            'inventory.sale', 'inventory.transfer', 'inventory.warehouse_manage',
                            'support.ai.manage', 'support.ai.inspect', 'support.ai.test',
                            'knowledge.manage', 'knowledge.approve'
                       )
                )
            THEN
                RAISE EXCEPTION 'invalid customer subaccount permission scope'
                    USING ERRCODE = '22023';
            END IF;

            SELECT role.id
            INTO v_portal_role_id
            FROM public.roles AS role
            WHERE role.tenant_id = p_tenant_id
              AND role.code = 'CUSTOMER_SUBACCOUNT'
              AND role.is_system = true
              AND role.status = 'active'
              AND role.deleted_at IS NULL;
            IF v_portal_role_id IS NULL THEN
                RAISE EXCEPTION 'customer subaccount role is unavailable'
                    USING ERRCODE = 'P0001';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM public.memberships AS membership
                WHERE membership.tenant_id = p_tenant_id
                  AND membership.login_identifier = v_login_identifier
                  AND membership.deleted_at IS NULL
            ) THEN
                RAISE EXCEPTION 'login account is already used by a member of the merchant'
                    USING ERRCODE = '23505';
            END IF;

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
                id, tenant_id, user_id, account_scope, parent_membership_id,
                login_identifier, status, joined_at, permission_version,
                permission_overrides, created_at, updated_at, deleted_at
            ) VALUES (
                p_membership_id, p_tenant_id, p_user_id, 'CUSTOMER_SUBACCOUNT',
                p_parent_membership_id, v_login_identifier, 'active', v_created_at, 1,
                p_permission_overrides, v_created_at, v_created_at, NULL
            );
            INSERT INTO public.membership_roles (
                id, tenant_id, membership_id, role_id, assigned_by_user_id,
                created_at, updated_at, deleted_at
            ) VALUES (
                gen_random_uuid(), p_tenant_id, p_membership_id,
                v_portal_role_id, p_actor_user_id,
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
